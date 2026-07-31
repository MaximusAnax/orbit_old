"""Command-line entrypoint.

Subcommands are ordered by the sequence you should actually use them in:

    orbit record      start the archive — do this first, and never stop it
    orbit scan        one-shot look at what the constraints currently find
    orbit backtest    replay the archive through the strategy
    orbit paper       run the full loop with simulated fills
    orbit live        the same loop with real money (three explicit switches)
    orbit status      what a running instance is doing
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

from orbit.config import Settings, get_settings
from orbit.core.fees import KalshiFees, PolymarketFees
from orbit.data.recorder import Recorder, RecorderConfig
from orbit.data.store import TickStore
from orbit.engine.executor import ExecutionMode, Executor
from orbit.engine.runner import Backtester, TradingRunner
from orbit.risk.engine import RiskEngine
from orbit.strategies.constraints import ConstraintScanner
from orbit.strategies.discovery import build_constraints_for
from orbit.venues.base import VenueAdapter

log = structlog.get_logger(__name__)


def setup_logging(settings: Settings) -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(message)s",
        stream=sys.stdout,
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            (
                structlog.processors.JSONRenderer()
                if settings.log_json
                else structlog.dev.ConsoleRenderer()
            ),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level.upper(), logging.INFO)
        ),
    )


def build_adapters(settings: Settings) -> dict[str, VenueAdapter]:
    """Construct only the venues that are actually configured."""
    adapters: dict[str, VenueAdapter] = {}
    if settings.has_kalshi:
        from orbit.venues.kalshi import KalshiAdapter, KalshiSigner

        adapters["kalshi"] = KalshiAdapter(
            KalshiSigner.from_file(
                settings.kalshi_key_id, settings.kalshi_private_key_path
            ),
            demo=settings.use_demo_endpoints,
        )
    if settings.has_polymarket:
        from orbit.venues.polymarket import PolymarketAdapter, PolymarketCredentials

        adapters["polymarket"] = PolymarketAdapter(
            PolymarketCredentials(
                private_key=settings.polymarket_private_key,
                api_key=settings.polymarket_api_key,
                api_secret=settings.polymarket_api_secret,
                api_passphrase=settings.polymarket_api_passphrase,
                funder=settings.polymarket_funder_address,
                signature_type=settings.polymarket_signature_type,
            )
        )
    return adapters


def build_runner(
    settings: Settings, adapters: dict[str, VenueAdapter], *, mode: ExecutionMode
) -> TradingRunner:
    scanner = ConstraintScanner(
        fee_models={"kalshi": KalshiFees(), "polymarket": PolymarketFees()},
        min_profit_pips=settings.min_profit_pips,
        max_size=settings.max_contracts_per_trade,
    )
    return TradingRunner(
        scanner=scanner,
        risk=RiskEngine(settings.risk_limits(), bankroll_pips=settings.bankroll_pips),
        executor=Executor(adapters, mode=mode),
        store=TickStore(settings.data_dir),
        scan_interval_s=settings.scan_interval_s,
    )


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


async def cmd_record(settings: Settings, args: argparse.Namespace) -> int:
    """Run the recorder. The first thing to deploy and the last to stop."""
    adapters = build_adapters(settings)
    if not adapters:
        print(
            "No venues configured. Set ORBIT_KALSHI_KEY_ID and "
            "ORBIT_KALSHI_PRIVATE_KEY_PATH, and/or ORBIT_POLYMARKET_PRIVATE_KEY.",
            file=sys.stderr,
        )
        return 1

    store = TickStore(settings.data_dir)
    recorder = Recorder(
        list(adapters.values()),
        store,
        RecorderConfig(
            poll_interval_s=settings.record_interval_s,
            max_markets_per_venue=settings.max_markets_per_venue,
        ),
    )
    log.info("record.start", venues=list(adapters), data_dir=str(settings.data_dir))
    try:
        await recorder.run(stream=args.stream)
    except KeyboardInterrupt:
        await recorder.stop()
    finally:
        for adapter in adapters.values():
            with contextlib.suppress(Exception):
                await adapter.close()
    return 0


async def cmd_scan(settings: Settings, args: argparse.Namespace) -> int:
    """One-shot scan. Answers 'is there anything here at all?'"""
    adapters = build_adapters(settings)
    if not adapters:
        print("No venues configured.", file=sys.stderr)
        return 1

    runner = build_runner(settings, adapters, mode=ExecutionMode.PAPER)
    try:
        for venue, adapter in adapters.items():
            markets = await adapter.list_markets(limit=args.limit)
            log.info("scan.markets", venue=venue, count=len(markets))
            for constraint in build_constraints_for(markets):
                runner.scanner.add(constraint)
            books = await asyncio.gather(
                *(adapter.get_book(m.venue_id) for m in markets),
                return_exceptions=True,
            )
            for book in books:
                if not isinstance(book, BaseException):
                    runner.observe(book)

        opportunities = runner.scanner.scan(runner.books)
        print(
            f"\n{len(runner.scanner.constraints)} constraints over "
            f"{len(runner.books)} markets\n"
        )
        if not opportunities:
            print("No violations found right now.")
            print(
                "\nThis is the expected result most of the time. Run "
                "`orbit record` continuously and check the archive over days,\n"
                "not the live book over seconds."
            )
        for opp in opportunities[:20]:
            print(f"  {opp}")
            print(f"      {opp.rationale}")
            print(f"      execution risk: {opp.execution_risk}")
    finally:
        for adapter in adapters.values():
            with contextlib.suppress(Exception):
                await adapter.close()
    return 0


async def cmd_backtest(settings: Settings, args: argparse.Namespace) -> int:
    """Replay the recorded archive through the strategy."""
    store = TickStore(settings.data_dir)
    stats = store.stats()
    if not stats["books"]["files"]:
        print(
            "No recorded data. Run `orbit record` first — there is no public\n"
            "historical order-book archive for these venues, so the backtest\n"
            "can only run on data you have collected yourself.",
            file=sys.stderr,
        )
        return 1

    since = datetime.now(UTC) - timedelta(days=args.days)
    books = list(store.read_books(start=since))
    if not books:
        print(f"No data in the last {args.days} days.", file=sys.stderr)
        return 1

    runner = build_runner(settings, {}, mode=ExecutionMode.BACKTEST)
    market_keys = {b.market_key for b in books}
    log.info("backtest.start", books=len(books), markets=len(market_keys))

    # Reconstruct the constraint set from the recorded market universe.
    from orbit.data.store import BOOK_DEPTH  # noqa: F401  (documented shape)

    for constraint in build_constraints_for(
        [], market_keys=sorted(market_keys)
    ):
        runner.scanner.add(constraint)

    report = await Backtester(runner).run(books)
    print(json.dumps(report, indent=2, default=str))
    return 0


async def cmd_trade(settings: Settings, args: argparse.Namespace) -> int:
    """Run the full loop: record, scan, risk-check, execute, serve, alert."""
    live = args.mode == "live"
    if live and not settings.is_live:
        print(
            "Refusing to trade live. All three switches must be set:\n"
            "  ORBIT_MODE=live\n"
            "  ORBIT_TRADING_ENABLED=true\n"
            "  ORBIT_USE_DEMO_ENDPOINTS=false",
            file=sys.stderr,
        )
        return 1

    adapters = build_adapters(settings)
    if not adapters:
        print("No venues configured.", file=sys.stderr)
        return 1

    mode = ExecutionMode.LIVE if live else ExecutionMode.PAPER
    runner = build_runner(settings, adapters, mode=mode)
    store = TickStore(settings.data_dir)
    recorder = Recorder(
        list(adapters.values()),
        store,
        RecorderConfig(
            poll_interval_s=settings.record_interval_s,
            max_markets_per_venue=settings.max_markets_per_venue,
        ),
    )

    # Seed the constraint registry from the live universe.
    for adapter in adapters.values():
        markets = await adapter.list_markets(limit=settings.max_markets_per_venue)
        for constraint in build_constraints_for(markets):
            runner.scanner.add(constraint)
    log.info(
        "trade.start",
        mode=mode.value,
        constraints=len(runner.scanner.constraints),
        **settings.describe(),
    )

    tasks = [
        asyncio.create_task(recorder.run(stream=False), name="recorder"),
        asyncio.create_task(runner.run(), name="runner"),
    ]
    if settings.api_token:
        tasks.append(asyncio.create_task(_serve_api(settings, runner, recorder)))

    try:
        await asyncio.gather(*tasks)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await runner.stop()
        await recorder.stop()
        for adapter in adapters.values():
            with contextlib.suppress(Exception):
                await adapter.close()
    return 0


async def _serve_api(
    settings: Settings, runner: TradingRunner, recorder: Recorder
) -> None:
    import uvicorn

    from orbit.api.server import create_app, state

    state.runner = runner
    state.recorder = recorder
    state.settings = settings
    config = uvicorn.Config(
        create_app(),
        host=settings.api_host,
        port=settings.api_port,
        log_level="warning",
    )
    log.info("api.serving", url=f"http://{settings.api_host}:{settings.api_port}")
    await uvicorn.Server(config).serve()


async def cmd_weather_study(settings: Settings, args: argparse.Namespace) -> int:
    """Measure how early the daily maximum locks in, from history alone.

    The only experiment here that needs no recorded prices: station
    observations go back decades, so the central claim of the weather strategy
    can be tested before any capital or waiting is committed.
    """
    from datetime import timedelta

    from orbit.data.weather import KNOWN_STATIONS, fetch_asos_history
    from orbit.strategies.weather_study import (
        build_certainty_curve,
        count_settled_thresholds,
    )

    stations = [s for s in KNOWN_STATIONS if not args.station or s.station_id == args.station]
    if not stations:
        print(f"Unknown station {args.station}. Known: "
              f"{', '.join(s.station_id for s in KNOWN_STATIONS)}", file=sys.stderr)
        return 1

    end = datetime.now(UTC)
    start = end - timedelta(days=args.days)
    for station in stations:
        print(f"\nFetching {station.station_id} ({station.name}), {args.days} days...")
        try:
            obs = await fetch_asos_history(station.station_id, start, end)
        except Exception as exc:
            print(f"  failed: {exc}", file=sys.stderr)
            continue
        if not obs:
            print("  no observations returned", file=sys.stderr)
            continue

        curve = build_certainty_curve(
            obs,
            timezone_offset_h=station.timezone_offset_h,
            station_id=station.station_id,
        )
        print()
        print(curve.format_table())

        hour = curve.first_hour_above(0.5)
        if hour is not None:
            p90 = next(
                (h.p90_remaining_rise for h in curve.hours if h.local_hour == hour), 6.0
            )
            counts = count_settled_thresholds(
                obs,
                timezone_offset_h=station.timezone_offset_h,
                thresholds=[float(t) for t in range(20, 111, 2)],
                at_local_hour=hour,
                plausible_remaining_rise=p90,
            )
            print(
                f"\nAt {hour}:00 local, on an average day "
                f"{counts.mean_settled_yes_thresholds:.1f} thresholds are already "
                f"settled YES and {counts.mean_settled_no_thresholds:.1f} settled NO "
                f"(2F grid, p90 rise allowance {p90:.1f}F)."
            )
        print(
            "\nThis measures CERTAINTY, not profit. Whether these settled "
            "contracts are still mispriced when the bot sees them requires "
            "recorded market data - run `orbit record` to find out."
        )
    return 0


def cmd_target(settings: Settings, args: argparse.Namespace) -> int:
    """What a monthly return target requires, and what it risks."""
    from orbit.risk.targets import (
        capacity_limited_return,
        feasibility_report,
        required_edge,
        simulate,
    )

    del settings
    print(feasibility_report())

    target = args.monthly / 100.0
    print(f"\n\nTo make {target:.0%}/month:")
    for dep in (0.10, 0.25, 0.50, 1.00):
        r = required_edge(monthly_target=target, deployment=dep)
        verdict = "plausible" if r.is_plausible else "IMPLAUSIBLE"
        print(f"  deploy {dep:>4.0%}/cycle -> need a {r.required_edge_pp:>5.2f}pp "
              f"edge   ({verdict})")

    print(f"\n\nCapacity ceiling (edge {args.edge}pp, "
          f"${args.capacity:,.0f} absorbable per cycle):")
    print(f"{'bankroll':>10} {'deployed':>10} {'monthly %':>10} {'monthly $':>11}")
    for bank in (5_000, 10_000, 25_000, 50_000, 100_000):
        cap = capacity_limited_return(
            bankroll=float(bank),
            edge_per_cycle=args.edge / 100.0,
            capacity_per_cycle=float(args.capacity),
        )
        print(f"{bank:>10,} {cap.deployed_per_cycle:>10,.0f} "
              f"{cap.monthly_return:>9.1%} {cap.monthly_dollars:>11,.0f}")
    print("\n  Note the last column. Past the capacity ceiling the dollar profit")
    print("  is flat: a bigger account buys a smaller percentage, not more money.")

    print("\n\nOne year at 97c on a believed 2pp edge, by deployment:")
    print(f"{'deploy':>7} {'edge sd':>8}  outcome")
    for dep in (0.10, 0.25, 0.50):
        for sd in (0.0, 0.02):
            sim = simulate(
                believed_edge=0.02, true_edge_sd=sd, deployment=dep, trials=2000
            )
            print(f"{dep:>6.0%} {sd * 100:>7.1f}pp  {sim.summary()}")
    print("\n  The median barely moves with edge uncertainty; the 5th percentile")
    print("  collapses. Estimation error does not cost you the average outcome,")
    print("  it costs you the bad ones.")
    return 0


async def cmd_status(settings: Settings, args: argparse.Namespace) -> int:
    """Query a running instance."""
    import httpx

    url = f"http://{settings.api_host}:{settings.api_port}/api/status"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                url, headers={"Authorization": f"Bearer {settings.api_token}"}
            )
            resp.raise_for_status()
            print(json.dumps(resp.json(), indent=2, default=str))
    except Exception as exc:
        print(f"Could not reach a running instance at {url}: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_config(settings: Settings, args: argparse.Namespace) -> int:
    """Print effective configuration. Never prints secrets."""
    print(json.dumps(settings.describe(), indent=2, default=str))
    if not settings.is_live:
        print("\nSimulation only — no real money can move in this configuration.")
    return 0


# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="orbit", description="Prediction-market trading system"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("record", help="record market data (start here)")
    p.add_argument("--stream", action="store_true",
                   help="use websockets instead of polling")
    p.set_defaults(func=cmd_record, is_async=True)

    p = sub.add_parser("scan", help="one-shot scan for constraint violations")
    p.add_argument("--limit", type=int, default=200, help="markets per venue")
    p.set_defaults(func=cmd_scan, is_async=True)

    p = sub.add_parser("backtest", help="replay the recorded archive")
    p.add_argument("--days", type=int, default=30)
    p.set_defaults(func=cmd_backtest, is_async=True)

    p = sub.add_parser("paper", help="run the loop with simulated fills")
    p.set_defaults(func=cmd_trade, is_async=True, mode="paper")

    p = sub.add_parser("live", help="run the loop with REAL MONEY")
    p.set_defaults(func=cmd_trade, is_async=True, mode="live")

    p = sub.add_parser(
        "weather-study",
        help="measure how early daily highs lock in (needs no recorded prices)",
    )
    p.add_argument("--days", type=int, default=365)
    p.add_argument("--station", default="", help="e.g. KNYC; omit for all")
    p.set_defaults(func=cmd_weather_study, is_async=True)

    p = sub.add_parser(
        "target", help="what a monthly return target requires, and risks"
    )
    p.add_argument("--monthly", type=float, default=10.0, help="target %% per month")
    p.add_argument("--edge", type=float, default=1.0, help="edge in pp per cycle")
    p.add_argument("--capacity", type=float, default=2500.0,
                   help="dollars absorbable per settlement cycle")
    p.set_defaults(func=cmd_target, is_async=False)

    p = sub.add_parser("status", help="query a running instance")
    p.set_defaults(func=cmd_status, is_async=True)

    p = sub.add_parser("config", help="show effective configuration")
    p.set_defaults(func=cmd_config, is_async=False)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    setup_logging(settings)
    result: Any = (
        asyncio.run(args.func(settings, args))
        if getattr(args, "is_async", False)
        else args.func(settings, args)
    )
    return int(result or 0)


if __name__ == "__main__":
    raise SystemExit(main())
