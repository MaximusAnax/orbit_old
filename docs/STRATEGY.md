# Strategy research

Findings from a 14-agent research program (venue recon → strategy hunt →
adversarial verification), reconciled against the fee arithmetic implemented in
`orbit.core.fees`.

**Method caveat, stated up front.** The venue domains and most documentation
hosts were blocked by network egress policy in the build environment. Facts
were sourced from official SDK source (reachable on PyPI/GitHub) and from web
search results, not from direct reads of the venue docs. Fee formulas and API
contracts are cross-checked and testable; qualitative claims about *frequency*
and *fill rates* are not verified and are flagged as such. Anything load-bearing
appears in [`VERIFICATION.md`](VERIFICATION.md) as a pre-live check.

---

## The bottom line

For a **$5,000 account**, one family of strategies survives scrutiny:
**logical-consistency arbitrage** on Kalshi's ladder and bucket markets.

It survives for reasons that are specific, not generic:

- **The edge is arithmetic.** A violated logical constraint is profitable in
  every feasible resolution. No probability estimate exists to be wrong about.
- **It tolerates latency.** Research puts the reaction window at *seconds* for
  date ladders and weather buckets, not microseconds. A cloud VPS is sufficient.
- **It fits the capital.** Individual violations are worth $200–$5,000 of
  position — at or below what this account can deploy anyway.
- **It is backtestable**, but only against data you record yourself.

Everything else either needs more capital, needs colocation, or does not survive
the fee math. Details below.

---

## Why fees dominate every conclusion

Kalshi taker fee: `ceil(0.07 × C × P × (1−P))`, rounded up **per fill**.

| Price | Fee/contract | Round-trip cost |
|---|---|---|
| 50c | 1.750c | ~3.50c |
| 75c | 1.313c | ~2.63c |
| 90c | 0.630c | ~1.26c |
| 95c | 0.333c | ~0.67c |
| 99c | 0.069c | ~0.14c |

Two consequences drive the entire design:

1. **Mid-book scalping is dead.** A 2c edge at 50c costs 3.5c to capture. The
   wings are 5–25x cheaper, which is why deep-in-the-money and tail-priced
   trades survive where mid-book trades cannot.
2. **Fragmentation is a real cost.** The cent ceiling applies per *fill*. A
   20-lot filling as twenty 1-lots pays 40c where one block pays 35c — 14% more
   for identical execution. Modelled via `n_fills`; the paper fill model charges
   per book level consumed. A backtest ignoring this overstates profit.

Polymarket historically charges **zero** trading fees and order placement is
gasless. That asymmetry means cross-venue pricing is not symmetric, and any arb
model treating the two legs identically overstates its edge on the Kalshi side.

---

## Tier 1 — implemented, trade these first

### Threshold vs bucket consistency (Kalshi weather)

Kalshi lists the same underlying twice: as ranges ("high 75–76°F") and as
thresholds ("high above 74°F"). The threshold is *definitionally* the sum of
the buckets above the cut. They are quoted by different participants and
routinely disagree.

Research rated this **high confidence** and the most repeatable accessible
opportunity: roughly 20 cities × 2 series (high/low) × 365 days of market-days
per year, with a reaction window of *minutes* around NWS forecast updates,
and $500–$5,000 of capacity per city-day.

Implemented as `ThresholdBucketConstraint`. Both directions are detected: buy
the buckets and sell the threshold, or the reverse.

### Date-ladder monotonicity

"X by March" implies "X by June", so March can never be worth more. Violations
persist until a maker on one rung reprices — **seconds**, not microseconds.
High confidence, $200–$5,000 per violation.

### Strike-ladder monotonicity

"Fed cuts ≥50bp" implies "≥25bp". "BTC above $110k" implies "above $100k".
High confidence. Slower on macro ladders (seconds to minutes); faster on crypto
ladders, which reprice continuously with spot — treat those as Tier 2 until
measured.

Both implemented as `MonotoneConstraint`. **Direction is the whole game**: a
violation means the narrow leg is *overpriced*, so it is sold and the broad leg
bought. The reverse pairing loses the full spread in the (narrow=False,
broad=True) state. A brute-force worst-case test caught exactly this bug during
development — it looked like an arbitrage and was a large naked bet.

Ladders build **all pairs**, not just adjacent rungs: non-adjacent rungs can be
inconsistent while every neighbouring pair looks fine.

---

## Tier 2 — implemented but gated off

### Partition / field-sum dutch books

If mutually exclusive, exhaustive outcomes sum below $1, buying the set pays $1
for certain. Rated high confidence *on the mechanism* — but research also
flagged scanning for `ΣYES < $1` **without verifying exhaustiveness** as "the
most expensive beginner error in this space".

Implemented as `PartitionConstraint`, discovered only at `INFERRED` confidence
and **disabled by default**. Enable per-event, by hand, after confirming the
listed markets genuinely partition the outcome space. Venue netting matters
enormously here: without it, shorting a field ties up the complement of every
leg instead of the true $1-per-set obligation.

### Cross-venue arbitrage

Real, but **resolution-criteria divergence is the dominant risk, not the price
gap**. Three different authorities can rule on nominally identical events:
Kalshi's internal team, Polymarket Global's UMA optimistic oracle, and
Polymarket US's own markets team — with different sources, dates and edge cases.
A mismatched pair is not an arbitrage; it is two opposing naked positions that
lose simultaneously.

Research also found taker/taker cross-venue arb at mid prices is *arithmetically
zero or negative*: breakeven needs ~3c of gross gap at 50c, but only ~0.57c at
95c. The trade is viable at the **tails**, not the middle.

Implemented as `CrossVenueConstraint` with `resolution_verified=False` by
default. It will not trade until a human reads both rulebooks.

---

## Tier 3 — needs more capital or infrastructure

| Strategy | Blocker at $5k |
|---|---|
| Polymarket liquidity-reward farming | Needs $10k–$50k per market to matter |
| Kalshi Liquidity Incentive Program | Needs $10k–$100k of resting capital |
| Kalshi tail-series market making | Rate-limit tiers are *earned by volume share*, not bought |
| Options-implied digital pricing | Needs a live options feed and sub-second reaction |
| ZQ/SR3 futures → Kalshi Fed markets | Needs a CME market-data subscription |
| Kalshi crypto settlement-window mechanics | Realistically needs colocation in AWS us-east-2 |

---

## What provably does not work

Recorded so these are never revisited. 61 dead ends were catalogued; these are
the ones most likely to be re-proposed.

**YES/NO parity arbitrage — structurally impossible on both venues.** Kalshi's
book is bids-only, and a YES bid at `X` *is* a NO ask at `$1−X`; the matching
engine cannot leave a parity violation resting. Polymarket's CTF Exchange has
MINT and MERGE match types that exist precisely to consume these. Orbit still
runs `ComplementConstraint` on every market, but as a **data-integrity check**
(a crossed book means a stale or corrupt feed), *not* as an alpha source. Do not
expect it to fire.

**Mid-book spread capture on Kalshi's maker-fee series.** Live enumeration found
149 of 12,199 series carry a maker fee; on those, a 1-cent spread is
mathematically dead.

**Sports in-game moneyline/spread/total consistency.** Measured: 290 combinatorial
episodes across 173 games, median return 101bps — but 76.9% capped at an average
executable size of a few hundred dollars, with a **median anomaly duration of
3.6 seconds**. Effectively zero at any serious scale, and an unwinnable latency
race against licensed low-latency stadium feeds.

**Kalshi vs CME FedWatch "arbitrage".** No fungible hedge exists: ZQ settles on
the arithmetic average of daily EFFR over the month; Kalshi settles on the
target-range decision. Different payoffs, not an arb.

**Kalshi BTC hourly vs Deribit options.** Expiry mismatch alone kills it —
Kalshi lists 15-minute and hourly markets; Deribit's shortest tenor is a daily
expiry.

**State-wins vs election-wins "consistency".** Marginal probabilities on 51
jurisdictions do not pin the joint distribution. This is model risk wearing a
logical constraint's clothing.

**Hedging inventory with US sportsbooks.** A standard −110/−110 line carries
~4.55% hold against ~1.75–3.5% round-trip on prediction markets. The prediction
market *is* the cheaper venue; hedging into a sportsbook adds cost.

**"Delta-neutral" reward farming.** Quoting both sides inside a reward band is
not delta-neutral — it is short a straddle with the reward pool as premium.

**Naive Avellaneda-Stoikov on binary contracts.** The inventory term has the
wrong sign of time dependence: binary contracts converge to 0 or 1 at expiry
rather than diffusing.

**Netting capital across Kalshi and Polymarket.** Structurally impossible; it
halves the return on capital of every cross-venue idea.

**Backtesting from either venue's public price history.** Polymarket's
`/prices-history` returns ≥12-hour granularity for closed markets; Kalshi offers
candlesticks and trades but no order-book archive. Any backtest built on these
is confidently wrong in both directions. This is the single strongest argument
for running the recorder from day one.

---

## Data and backtesting

**There is no usable public order-book history for these venues.** The archive
can only be built forward in time. `orbit record` writes date- and
venue-partitioned Parquet and should run continuously from before you decide
whether to trade.

What can be tested how:

| Claim | Method |
|---|---|
| Do violations occur, and how often? | Backtest against the recorded archive |
| Are they large enough after fees? | Backtest; fee model is exact |
| **Can they actually be filled?** | **Paper trading only** — the archive cannot tell you whether a quote would have vanished when touched |

The third row is why the promotion gate weights fill rate as heavily as PnL. A
high detection rate with a low fill rate means the violations are stale quotes,
and no amount of backtesting will reveal that.

**Backtest limitation to know about:** reconstructing constraints from recorded
market *keys* alone recovers parity only, not ladders — ladder structure needs
the market metadata. The recorder snapshots the market universe daily for this
reason; a backtest run without it silently tests less than you think.

---

## Position sizing

Quarter Kelly, capped at 0.5. Growth as a function of stake peaks at full Kelly
and returns to zero near *twice* it, so overbetting a genuinely profitable edge
earns nothing and beyond that loses money on a winning strategy. Staking
fraction `c` of Kelly retains about `c(2−c)` of optimal growth: half Kelly keeps
~75%, quarter Kelly ~44%. Giving up half the theoretical growth to survive a
materially wrong probability estimate is the right trade when the estimate is an
estimate.

Correlation is the limit that actually protects a small account. Ten contracts
on one election are not ten bets; variance of the sum scales as `n + n(n−1)ρ`,
so per-position stake divides by `sqrt(1 + (n−1)ρ)`. At ρ=0.7 with five
positions that is a 0.5x haircut. Sizing each leg at "quarter Kelly"
independently would be betting well over full Kelly on the single driver.

---

## Open questions

Unresolved, and worth revisiting with real data:

1. **How often do ladder violations actually occur on Kalshi weather markets?**
   The single most important unknown. The archive answers it.
2. **What fraction are fillable?** Paper trading answers it.
3. Does the per-fill fee ceiling behave as documented? (See `VERIFICATION.md`.)
4. Are Kalshi's maker fees still $0 on the traded series?
5. Does the crypto-ladder variant need colocation, or is a VPS enough?
