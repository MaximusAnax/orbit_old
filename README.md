# Orbit

An automated trading system for prediction markets (Kalshi and Polymarket),
built around logical-consistency arbitrage, with a market-data recorder, a
backtester, hard risk limits, and a dashboard.

---

## Read this before anything else

You asked for a system that makes money. Here is the honest version of what
this can and cannot do, stated up front because every number below changes how
you should use it.

**The fee math rules out most of what sounds appealing.** Kalshi charges takers
`ceil(0.07 × contracts × P × (1−P))`, rounded up to the next cent *per fill*.
At mid-book that is 1.75c per contract, so a round trip costs ~3.5c on a $1
contract. A 2-cent scalp at 50c is not a thin edge — it is a guaranteed loss.
The same 2-cent edge at 95c clears comfortably, because the fee there is 0.33c.
This single asymmetry eliminates the majority of "obvious" strategies, and the
codebase encodes it in `orbit.core.fees` with tests pinning it to published
values.

**At under $5,000, capital is the binding constraint, not ideas.** Positions are
fully collateralised — no leverage. Shorting a 5c longshot ties up 95c per
contract to earn 5c. A 2% risk-free return that locks capital until a
settlement three months out is a worse trade than it looks, which is why the
system ranks opportunities by *return on capital deployed* rather than by
absolute profit.

**The strategy that survives scrutiny is narrow.** Research (14 agents, adversarial
verification, findings in [`docs/STRATEGY.md`](docs/STRATEGY.md)) converged on
logical-consistency arbitrage: contracts whose prices must satisfy an arithmetic
relationship, where a violation is profitable in *every* resolution. No forecast
is required and there is no model to be wrong about. The honest caveats:

- Violations are **rare**. Most scans find nothing. That is the expected result.
- Some are **stale quotes** that vanish when touched. The promotion gate
  measures fill rate specifically to catch this before real money is committed.
- Faster participants compete for the same violations.

**Several strategies people assume work, do not.** YES/NO parity arbitrage is
structurally impossible on both venues — the exchanges' own matching engines
harvest it (Kalshi's book is bids-only; Polymarket's CTF mints and merges pairs
directly). Cross-venue arbitrage is dominated by *resolution-criteria
divergence*, not by the price gap. Backtesting from either venue's public price
history is invalid, because the granularity is ≥12 hours for closed markets.
The full list, with the reasoning, is in `docs/STRATEGY.md`.

**What this system is actually best at, month one:** building a market-data
archive nobody else has. There is no usable public order-book history for these
venues, so the archive can only be built forward in time. Every day the recorder
is not running is a day of backtest that cannot be recovered later. Run
`orbit record` today, even before you decide whether to trade.

**Realistic expectations.** A plausible good outcome at this capital is a small
number of genuine arbitrage fills per week, netting low single-digit percentage
returns per month on deployed capital, with meaningful variance and long flat
stretches. A plausible bad outcome is that violations prove unfillable in
practice and the system correctly refuses to trade — in which case it will have
cost you the VPS bill and produced a valuable dataset. Both are real outcomes.
Anyone promising more than this from $5k is selling something.

Nothing here is investment advice, and no part of this system has traded real
money yet.

---

## What is built

| Component | Purpose |
|---|---|
| `orbit.core` | Integer-pip money, exact fee models, domain types |
| `orbit.venues` | Kalshi and Polymarket adapters, normalised to one interface |
| `orbit.data` | Continuous recorder, partitioned Parquet archive |
| `orbit.strategies` | Constraint engine and discovery |
| `orbit.risk` | Fractional-Kelly sizing, exposure limits, kill switch |
| `orbit.engine` | Executor, trading loop, backtester, promotion gate |
| `orbit.api` | Dashboard, kill switch, funding view |
| `orbit.alerts` | Telegram alerts, daily summary |

274 tests, including property-based checks that PnL accounting conserves cash
exactly and that no reported "arbitrage" can lose in any feasible outcome.

---

## Quickstart

```bash
uv venv && uv pip install -e ".[dev,analysis]"
cp .env.example .env          # then edit
orbit config                  # confirm: "simulation only"
```

### 1. Start recording (do this first)

```bash
orbit record
```

This is the only step that is genuinely urgent. It needs credentials for market
data but never places an order.

### 2. See what the constraints find

```bash
orbit scan
```

Prints current violations. Finding nothing is normal and expected.

### 3. Backtest once you have data

```bash
orbit backtest --days 30
```

Replays your recorded archive through the same code the live loop runs.

### 4. Paper trade

```bash
orbit paper
```

Full loop with simulated fills against live books. Dashboard at
`http://127.0.0.1:8080`. Leave this running for at least two weeks.

### 5. Go live — only after the gate clears

The promotion gate (`orbit status`) requires 50+ completed trades, 14+ days,
positive PnL after modelled fees, and a fill rate above 50%. Going live then
requires three independent switches:

```bash
ORBIT_MODE=live
ORBIT_TRADING_ENABLED=true
ORBIT_USE_DEMO_ENDPOINTS=false
```

Start with a fraction of your capital, not all of it.

---

## Monitoring and money

- **Dashboard** — PnL, positions, risk gauges against each limit, live
  opportunities, trade log, and a kill-switch button.
- **Telegram** — critical alerts only (kill switch, position mismatch), plus a
  daily summary that sends unconditionally, so silence means the process is down.
- **`GET /api/funding`** — balances and exact deposit/withdrawal steps.

Money movement is deliberately **not automated**. A credential that can move
funds off-venue inside an unattended process is a much larger blast radius than
one that can only trade. The system tells you what to do; you click the button.

---

## Safety

Defaults are paper mode, demo endpoints, trading disabled. Beyond that:

- Kill switch is one-way and requires a named human to reset.
- Automatic halts on daily loss (5%) and drawdown (15%).
- Per-market, per-event and per-venue exposure caps, with a correlation penalty
  because ten contracts on one election are not ten independent bets.
- Quarter Kelly by default, capped at 0.5 — growth peaks at full Kelly and
  reaches zero near twice it, so overbetting a real edge earns nothing.
- Stale market data blocks execution.
- Duplicate order IDs are rejected, so a retry cannot double-fill.
- Multi-leg trades are all-or-nothing; partial fills are unwound immediately.

---

## Documentation

- [`docs/RETURNS.md`](docs/RETURNS.md) — **what returns are actually
  achievable**, with base rates, documented winners and losers, and the honest
  paths to more money. Read this before setting a target.
- [`docs/STRATEGY.md`](docs/STRATEGY.md) — research findings, what works, what
  provably does not, and why
- [`docs/RUNBOOK.md`](docs/RUNBOOK.md) — operations, incidents, go-live checklist
- [`docs/VERIFICATION.md`](docs/VERIFICATION.md) — what must be checked against
  the live venues before trading real money
