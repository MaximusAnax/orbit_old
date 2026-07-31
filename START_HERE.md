# Start here

Everything in this project is blocked on one question: **is there a real edge?**
Every dollar figure anywhere in these docs is conditional on it, and right now
it is an assumption, not a measurement.

So the plan is ordered by *information per dollar spent*, not by how quickly it
starts trading. Total spend before you learn whether this works: **about $30.**

---

## Today — 30 minutes, $0

```bash
git clone <your-repo> && cd orbit
uv venv && uv pip install -e ".[dev,analysis]"
orbit config                      # should say "simulation only"
orbit target --monthly 10         # the feasibility maths, no account needed
orbit weather-study --days 365    # THE experiment
```

`weather-study` pulls a year of free NWS station history and measures, per city
and per hour, **what fraction of days had already hit their daily maximum by
that hour.** No account, no capital, no waiting — the data already exists.

**How to read the result:**

| Outcome | What it means | What to do |
|---|---|---|
| >70% settled by 15:00 local | The core premise holds. There are hours every day when the outcome is *known* and contracts may still be mispriced. | Continue to step 2. |
| 40–70% by 15:00 | Weaker but alive. The edge would be thinner and more selective. | Continue, with lowered expectations. |
| <40%, or only settles after 20:00 | The premise fails. Intraday certainty arrives too late to trade. | **Stop.** You have saved yourself a month and $5,000. |

This is genuinely the highest-value thing you can do, and it costs nothing.

---

## This week — ~1 hour, ~$5/month

Two things in parallel, because both have lead times.

**1. Open a Kalshi account and generate an API key.** KYC takes a day or two.
You need the key for market data even if you never trade. Put the RSA private
key in `secrets/kalshi.pem` and fill in `.env`.

**2. Start the recorder on anything that runs 24/7** — a $5/month VPS is fine.

```bash
orbit record
```

This is the only genuinely *urgent* item, and it never places an order. There is
no public order-book history for these venues, so the archive can only be built
forward in time. Every day it is not running is a day of backtest you can never
recover. Start it before you decide whether to trade at all.

Check it is alive: `orbit status`, or the dashboard on `:8080`.

---

## Weeks 2–4 — $0

```bash
orbit paper
```

Full trading loop, simulated fills, real live books. Watch **fill rate**, not
PnL. A high detection rate with a low fill rate means the opportunities are
stale quotes that evaporate when touched — which is the single most likely way
this fails, and the promotion gate is built to catch it.

Also run `orbit backtest --days 14` once the archive has some depth.

**Decision point.** `orbit status` reports the gate: 50+ trades, 14+ days,
positive PnL after modelled fees, fill rate >50%. If it does not clear, do not
override it. That gate exists for the version of you that is impatient in three
weeks.

---

## Week 5+ — $500, not $5,000

Only if the gate cleared. Fund **$500**, set the three switches, and run live.

```bash
ORBIT_MODE=live
ORBIT_TRADING_ENABLED=true
ORBIT_USE_DEMO_ENDPOINTS=false
```

The purpose of this money is **measurement, not profit.** Budget to lose
$50–150 and treat it as tuition. You are measuring three things paper trading
cannot tell you:

- realised fee per contract vs. the formula
- actual fill rates on resting orders
- **5-minute markouts on every fill** — the critical one

If your markouts are negative, you are the slow side of every trade. That is a
documented failure mode, it is not fixable by trying harder, and it means stop.

---

## Then, and only then

Scale to $2,000, then $5,000, at **25% deployment** — never 50%, where ruin risk
roughly triples for a doubled median. Cap any correlated cluster at 5% of the
account. Treat all cities on a given day as 3–5 bets, not 20: one busted
forecast hits every station at once.

And the thing that actually gets you to $1,000/month, which is not a return
rate:

- **Feed it from income.** At $5,000 and 3%/month the system earns $150 while
  $500/month of savings does three times as much work. Returns only overtake a
  $500 contribution past ~$17,000.
- **Add capacity, not just capital.** Past the depth ceiling, a bigger account
  buys a *smaller percentage, not more dollars* (`orbit target` shows this).
  More cities, more series, both venues — breadth is what raises the ceiling.
- **Never withdraw at this size.** Withdrawing $1,000/month empties a $5,000
  account in six months even at a world-class 5%/month.

---

## Things that will not work

Measured, not guessed. Do not spend weeks rediscovering these:

- **15-minute crypto binaries** — 4,904 strategies backtested: 102 profitable,
  median −14.5%/month.
- **Latency plays on free data** — one operator went 0 for 32 and retired it.
  ECMWF open data is ~2 hours delayed; Kalshi's websocket is ~25ms.
- **Contracts under 15c** — Kalshi contracts below 10c return under 40c on the
  dollar.
- **Parlays** — 19c lost per dollar, versus 6c on straights.
- **Anyone selling a bot or a signal.**

---

## The honest summary

- If `weather-study` shows a steep, early certainty curve **and** paper trading
  shows real fills, you have evidence of something real and the correct response
  is to add capital slowly.
- If either fails, the correct response is to stop, and you will have spent
  about $30 to find out.
- The base rate says stopping is the likelier outcome: ~70% of prediction-market
  accounts lose money, and profit above $1,000 *in total* puts a wallet in the
  top 0.51%.

Both outcomes are wins compared with deploying $5,000 against an unmeasured
hypothesis, which is priced at a **median 42% loss**.

Full reasoning: [`docs/RETURNS.md`](docs/RETURNS.md) ·
[`docs/STRATEGY.md`](docs/STRATEGY.md) ·
[`docs/VERIFICATION.md`](docs/VERIFICATION.md) (check before live money) ·
[`docs/RUNBOOK.md`](docs/RUNBOOK.md)
