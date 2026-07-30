"""Recorder resilience and archive integrity.

The recorder's job is to still be running, and still be correct, after a week
of transient venue failures. These tests inject the failures that would
otherwise only be discovered in production at an inconvenient hour.
"""

from __future__ import annotations

import asyncio
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from orbit.core.types import Market, MarketStatus, Venue
from orbit.data.recorder import Recorder, RecorderConfig
from orbit.data.store import TickStore
from tests.fakes import FakeAdapter


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as tmp:
        yield TickStore(tmp, flush_rows=10_000, flush_seconds=1e9)


async def run_briefly(recorder: Recorder, seconds: float = 0.35, *, stream: bool) -> None:
    """Run the recorder, then shut it down the way production does.

    ``stop()`` cancels the venue tasks and ``run()`` treats that as a graceful
    exit, so the run task completes normally rather than propagating
    ``CancelledError``. Awaiting it here also asserts that shutdown actually
    terminates instead of hanging.
    """
    task = asyncio.create_task(recorder.run(stream=stream))
    await asyncio.sleep(seconds)
    await recorder.stop()
    await asyncio.wait_for(task, timeout=5.0)


class TestUniverseSelection:
    def test_skips_inactive_markets(self, store):
        now = datetime.now(UTC)
        markets = [
            Market(Venue.KALSHI, "A", "a", "E", MarketStatus.ACTIVE,
                   close_time=now + timedelta(days=1)),
            Market(Venue.KALSHI, "B", "b", "E", MarketStatus.SETTLED,
                   close_time=now + timedelta(days=1)),
            Market(Venue.KALSHI, "C", "c", "E", MarketStatus.CLOSED,
                   close_time=now + timedelta(days=1)),
        ]
        rec = Recorder([FakeAdapter()], store)
        assert [m.venue_id for m in rec._select_markets(markets)] == ["A"]

    def test_skips_markets_beyond_the_horizon(self, store):
        now = datetime.now(UTC)
        markets = [
            Market(Venue.KALSHI, "NEAR", "n", "E", MarketStatus.ACTIVE,
                   close_time=now + timedelta(days=2)),
            Market(Venue.KALSHI, "FAR", "f", "E", MarketStatus.ACTIVE,
                   close_time=now + timedelta(days=400)),
        ]
        rec = Recorder([FakeAdapter()], store, RecorderConfig(max_days_to_close=30))
        assert [m.venue_id for m in rec._select_markets(markets)] == ["NEAR"]

    def test_skips_already_closed_markets(self, store):
        now = datetime.now(UTC)
        markets = [
            Market(Venue.KALSHI, "PAST", "p", "E", MarketStatus.ACTIVE,
                   close_time=now - timedelta(hours=1)),
        ]
        rec = Recorder([FakeAdapter()], store)
        assert rec._select_markets(markets) == []

    def test_prefers_soonest_close_and_caps_count(self, store):
        now = datetime.now(UTC)
        markets = [
            Market(Venue.KALSHI, f"M{i}", "m", "E", MarketStatus.ACTIVE,
                   close_time=now + timedelta(days=i + 1))
            for i in range(20)
        ]
        rec = Recorder([FakeAdapter()], store, RecorderConfig(max_markets_per_venue=3))
        picked = rec._select_markets(markets)
        assert [m.venue_id for m in picked] == ["M0", "M1", "M2"]


class TestPolling:
    async def test_refreshes_the_universe_on_the_very_first_iteration(self, store):
        """Startup must not wait a full refresh interval before doing anything.

        The event loop clock has an arbitrary origin, so a "last refreshed at
        0.0" sentinel silently means "not due yet" on a freshly started
        process. That made the recorder idle for its first fifteen minutes -
        invisible in logs and dependent on clock origin, so the other tests
        passed or failed by luck. A long refresh interval here would mask the
        bug, so it is deliberately set larger than the test runtime.
        """
        adapter = FakeAdapter()
        rec = Recorder(
            [adapter],
            store,
            RecorderConfig(poll_interval_s=0.01, universe_refresh_s=86_400),
        )
        await run_briefly(rec, seconds=0.2, stream=False)
        assert rec.health["kalshi"].markets_tracked > 0
        assert rec.health["kalshi"].books_recorded > 0

    async def test_records_books_and_reports_health(self, store):
        adapter = FakeAdapter()
        rec = Recorder([adapter], store, RecorderConfig(poll_interval_s=0.02))
        await run_briefly(rec, stream=False)

        health = rec.health["kalshi"]
        assert health.books_recorded > 0
        assert health.connected
        assert health.last_book_at is not None
        assert not health.is_stale

        store.flush()
        assert list(store.read_books(venue="kalshi"))

    async def test_survives_transient_venue_errors(self, store):
        """A failing venue must degrade coverage, never stop the recorder."""
        adapter = FakeAdapter()
        adapter.fail_next_n = 3
        rec = Recorder(
            [adapter],
            store,
            RecorderConfig(poll_interval_s=0.01, reconnect_base_s=0.01,
                           reconnect_max_s=0.02),
        )
        await run_briefly(rec, seconds=0.4, stream=False)
        assert rec.health["kalshi"].error_count > 0
        assert rec.health["kalshi"].books_recorded > 0, "should recover and record"

    async def test_honours_rate_limits(self, store):
        adapter = FakeAdapter()
        adapter.rate_limit_next_n = 2
        rec = Recorder(
            [adapter],
            store,
            RecorderConfig(poll_interval_s=0.01, reconnect_base_s=0.01),
        )
        await run_briefly(rec, seconds=0.35, stream=False)
        assert rec.health["kalshi"].books_recorded > 0

    async def test_multiple_venues_are_independent(self, store):
        """One venue dying must not take the other's coverage with it."""
        good = FakeAdapter(Venue.KALSHI)
        bad = FakeAdapter(Venue.POLYMARKET)
        bad.fail_next_n = 1000  # permanently broken
        rec = Recorder(
            [good, bad],
            store,
            RecorderConfig(poll_interval_s=0.01, reconnect_base_s=0.01,
                           reconnect_max_s=0.02),
        )
        await run_briefly(rec, seconds=0.4, stream=False)
        assert rec.health["kalshi"].books_recorded > 0
        assert rec.health["polymarket"].books_recorded == 0
        assert rec.health["polymarket"].error_count > 0


class TestStreaming:
    async def test_records_from_stream(self, store):
        adapter = FakeAdapter()
        rec = Recorder([adapter], store, RecorderConfig())
        await run_briefly(rec, seconds=0.25, stream=True)
        assert rec.health["kalshi"].books_recorded > 0

    async def test_reconnects_after_a_dropped_stream(self, store):
        adapter = FakeAdapter()
        adapter.stream_drops_after = 5
        rec = Recorder(
            [adapter],
            store,
            RecorderConfig(reconnect_base_s=0.01, reconnect_max_s=0.02),
        )
        await run_briefly(rec, seconds=0.4, stream=True)
        assert rec.health["kalshi"].reconnects > 0
        assert rec.health["kalshi"].books_recorded > 5, "must resume after reconnect"


class TestFiltering:
    async def test_one_sided_books_are_not_recorded(self, store):
        """Rows of nulls are worse than no rows: they pollute the archive."""
        adapter = FakeAdapter()
        adapter.set_book("TEST-0", [(4500, 100)], [])  # bid only
        rec = Recorder([adapter], store, RecorderConfig(require_two_sided=True))
        assert not rec._accept(await adapter.get_book("TEST-0"))

    async def test_crossed_books_are_still_recorded(self, store):
        """A crossed book may be the arbitrage we are hunting; keep it."""
        adapter = FakeAdapter()
        adapter.set_book("TEST-0", [(5500, 100)], [(4500, 100)])
        rec = Recorder([adapter], store, RecorderConfig())
        book = await adapter.get_book("TEST-0")
        assert book.is_crossed
        assert rec._accept(book)


class TestArchiveDurability:
    async def test_data_is_flushed_on_shutdown(self, store):
        """A clean stop must never leave the last minute of ticks in RAM."""
        adapter = FakeAdapter()
        rec = Recorder([adapter], store, RecorderConfig(poll_interval_s=0.01))
        await run_briefly(rec, seconds=0.2, stream=False)
        assert store.stats()["buffered"]["books"] == 0
        assert list(store.read_books(venue="kalshi"))

    def test_partitioned_by_venue_and_date(self, store):
        from orbit.venues.base import normalize_two_sided_book

        for venue in ("kalshi", "polymarket"):
            for day in (29, 30):
                store.record_book(
                    normalize_two_sided_book(
                        market_key=f"{venue}:X",
                        timestamp=datetime(2026, 7, day, 12, tzinfo=UTC),
                        bids=[(4500, 10)],
                        asks=[(4700, 10)],
                    )
                )
        store.flush()
        root = Path(store.root)
        assert (root / "books" / "venue=kalshi" / "date=2026-07-29").exists()
        assert (root / "books" / "venue=kalshi" / "date=2026-07-30").exists()
        assert (root / "books" / "venue=polymarket" / "date=2026-07-30").exists()
        assert len(list(store.read_books(venue="kalshi"))) == 2
        assert len(list(store.read_books(venue="kalshi", day="2026-07-30"))) == 1

    def test_reads_back_in_timestamp_order_across_parts(self, store):
        """Replay correctness depends on global ordering, not per-file order."""
        from orbit.venues.base import normalize_two_sided_book

        base = datetime(2026, 7, 30, tzinfo=UTC)
        for chunk in range(3):
            for i in range(20):
                n = chunk * 20 + i
                store.record_book(
                    normalize_two_sided_book(
                        market_key="kalshi:X",
                        timestamp=base + timedelta(seconds=n),
                        bids=[(4500 + n, 10)],
                        asks=[(4700 + n, 10)],
                    )
                )
            store.flush()  # forces a separate part file per chunk

        books = list(store.read_books(market_key="kalshi:X"))
        assert len(books) == 60
        stamps = [b.timestamp for b in books]
        assert stamps == sorted(stamps)
        assert books[0].best_bid_pips == 4500
        assert books[-1].best_bid_pips == 4559
