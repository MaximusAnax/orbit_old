# What returns are actually achievable

Written because the target moved to **$1,000/month of return on $5,000**
(reinvested, not withdrawn), with an aspiration far higher, prompted by a
second-hand account of someone making $300k in six months.

This document exists to make that decision on evidence. Sources are cited
throughout. Where a number could not be verified it says so.

---

## 1. The arithmetic

| Framing | What it requires |
|---|---|
| $1,000/mo on $5,000, **month one** | 20%/month |
| Sustained at 20%/month, compounded | **791%/year** |
| Sustained 24 months | $5,000 → ~$397,000 |
| Sustained 36 months | $5,000 → ~$3.54M |
| "$300k in 6 months" from a retail account | **~99%/month for six consecutive months** (60.9×) |

For scale: Renaissance Medallion, the best-documented sustained return in
finance, did roughly 39% *per year* net over three decades — and closed to
outside money because the strategy could not absorb more capital. On $5,000
that rate is **$139/month**.

### Compounding vs withdrawing — these are different problems

The target is **$1,000/month of return, reinvested**, not $1,000/month
withdrawn. That distinction matters more than anything else in this document,
so both cases are given.

**If profits are withdrawn**, the account never builds a buffer and the
arithmetic is brutal: at a sustained 5%/month — world-class for this asset
class — withdrawing $1,000/month empties a $5,000 account in **six months**,
deterministically, before variance. At 10%/month it lasts seven. Sizing up to
chase the target makes ruin near-certain (P(ruin within 12 months) ~93.7% at a
genuine 2pp edge sized to target). **Do not withdraw from a $5,000 account.**

**If profits compound**, the picture changes completely, because $1,000 is a
shrinking percentage of a growing account:

| Month | Account | % needed that month for $1,000 |
|---|---|---|
| 1 | $5,000 | **20.0%** |
| 3 | $7,000 | 14.3% |
| 6 | $10,000 | 10.0% |
| 12 | $16,000 | 6.2% |
| 24 | $28,000 | 3.6% |
| 36 | $40,000 | **2.5%** |

The first year is the hard part. After that the target eases into the range a
real edge could plausibly sustain.

### The right way to state the goal

**$1,000/month is an account-size milestone, not a return-rate milestone.**
At a sustainable rate `r`, it simply requires an account of `$1,000 / r`:

| Sustained rate | Annualised | Account needed | Years from $5,000, no contributions |
|---|---|---|---|
| 1%/month | 13% | $100,000 | 25.1 |
| **2%/month** | **27%** | **$50,000** | **9.7** |
| 3%/month | 43% | $33,333 | 5.3 |
| 5%/month | 80% | $20,000 | 2.4 |

Compounding alone from $5,000 is slow, because the base is small. Adding
outside savings changes it dramatically:

| Sustained rate | +$500/month | +$2,000/month |
|---|---|---|
| 1%/month | 8.4 years | 3.2 years |
| **2%/month** | **3.9 years** | **1.6 years** |
| 3%/month | 2.4 years | 1.0 year |
| 5%/month | 1.2 years | 0.5 years |

**The practical consequence: for roughly the first two years your savings rate
matters more than your trading edge.** At $5,000 and 3%/month the system earns
$150/month while $500/month of savings contributes over three times as much.
Trading returns only overtake a $500/month contribution once the account passes
about $17,000. Until then, the edge's job is to *exist and be validated*, not
to pay you.

The sharpest way to see the size of the ask: **a trader compounding 20%/month
for three years from $5,000 would end with more lifetime profit than Domer —
the #1 all-time Polymarket trader — has accumulated in 18 years.**

---

## 2. What the big wins actually were

### Théo / "Fredi9999" — the $85M election trade

The story everyone has heard, and it does not mean what it appears to.

- Capital deployed: **~$30M scaling to ~$80M** across 11 accounts. He told the
  WSJ this was *the majority of his liquid assets*, and that a Harris win meant
  losing most of it.
- Profit: ~$85M. **Return on capital: roughly 1.0–1.1×** over five to six
  weeks. Not 60×. The dollar figure is large because the *capital* was large.
- Background: a **former professional bank trader**, not a retail participant.
- The edge was **an information purchase, not a technique**: he commissioned
  bespoke YouGov swing-state polling using the "neighbour question" to capture
  social-desirability bias. Cost is unverified but a multi-state commissioned
  YouGov panel is a five-to-six-figure expense.
- He was **down ~$3M** at one point along the way.

Sources: [CNBC](https://www.cnbc.com/2024/10/24/polymarket-trump-french-election-bet.html),
[Forbes](https://www.forbes.com/sites/dereksaul/2024/10/24/who-is-polymarkets-trump-whale-site-reveals-french-trader-bet-28-million-on-trump-win/),
[Yahoo/BI](https://finance.yahoo.com/news/polymarket-whale-actually-made-85-050139914.html)

To replicate the *return* at $5,000 you would make $5,250. To replicate the
*dollars* you would need $80M and to be willing to lose it.

### Domer — the most useful data point available

The best-documented professional in the space. Trading political markets since
2007.

- **~$4.0–4.8M lifetime profit** on **~$300M of cumulative volume** across
  more than 5,000 markets.
- **Return on volume: ~1.6%.** That is the realistic magnitude of durable edge
  in this asset class, from the best-known practitioner, over 18 years.
- He **loses more individual bets than he wins**; the winners are bigger.
- Bankroll never disclosed, so his return on capital is unknowable. This is the
  recurring pattern: the P&L is public, the denominator never is.
- Now only intermittently active, well below 2023–24 levels — consistent with
  edge decay as institutions arrived.

Sources: [predicting.top](https://predicting.top/account/Domer),
[onchaintimes interview](https://www.onchaintimes.com/a-chat-with-domer-the-1-trader-on-polymarket/),
[60 Minutes](https://www.cbsnews.com/news/who-is-making-bets-on-polymarket-60-minutes/)

### The people actually making money on these venues

Bloomberg's Odd Lots profiled them in July 2026 under the headline *"These Are
The Only People Making Real Money on Kalshi and Polymarket."* Their disclosed
methods: one **rebuilt the BLS CPI computation from source components** to
forecast inflation prints; others **physically door-knocked in Dallas** for
election edge.

Their own summary: *"if you started trading right now, you'd probably lose your
shirt."*

That is the honest template. It is not a strategy — it is a job.

---

## 3. The other half of the distribution

The 2024 election did not create winners. It *sorted* an existing population,
and the losing half is simply written about less.

| Account | Loss |
|---|---|
| beachboy4 | **−$2.0M in 35 days** |
| comon119 | −$8.7M |
| Anonymous | −$9.8M |
| AnonBidenBull | −$2M |
| Anonymous (anti-Trump, 2024) | −$4.6M |

**beachboy4 is the single most instructive case here: a 51% win rate produced a
$2M loss.** He bought consensus at 51–67c — precisely where Kalshi's fee curve
peaks. Win rate is not edge. Sizing and price paid are edge.

Sources: [incrypted](https://incrypted.com/en/polymarket-trader-lost-over-2m-in-35-days-due-to-risk-management-errors/),
[polylosers.com](https://polylosers.com/)

---

## 4. Base rates — the decisive section

Polymarket, 1.6M accounts active since Nov 2022 (WSJ, May 2026) plus on-chain
analysis of 95M transactions:

| Metric | Value |
|---|---|
| Accounts that **lose** money | **~70%** |
| Profits captured by the top 0.1% | **67%** |
| Median account | **down $1–$100** |
| Bottom decile | **−$4,000 average** |
| Wallets with profit **> $1,000** | **0.51%** |
| Wallets with profit > $10,000 | 0.32% |
| Wallets with profit **> $100,000** | **0.033%** (840 of ~2.5M) |
| In profit at all (Apr 2026) | **15.9%** |

Sources: [WSJ](https://www.wsj.com/finance/investing/everyone-loses-except-a-few-sharks-on-prediction-markets),
[Bloomberg](https://www.bloomberg.com/news/newsletters/2026-04-29/most-traders-lose-on-polymarket-and-winners-look-like-bots),
[CoinDesk](https://www.coindesk.com/markets/2026/04/29/a-tiny-group-is-winning-on-polymarket-as-under-1-of-wallets-take-half-the-profits)

Read the $1,000 row carefully. **Making $1,000 in total, ever, puts a wallet in
the top 0.51%.** The target is $1,000 *per month, indefinitely*.

---

## 5. About the $300k story

Take it seriously as a data point, then apply the base rate.

There is **documented, litigated evidence that both platforms paid people to
fabricate winning-bet content.** Polymarket paid creators to post fake bet
videos in a campaign reaching ~140 million views; the CFTC is investigating and
a consumer class action has been filed, alleging Polymarket **built fake
websites so influencers could stage payouts**. Kalshi has separately been
reported paying "clippers" to post fake winning bets, generally undisclosed as
advertising — one paid partner was a 15-year-old streamer.

Sources: [Qz](https://qz.com/polymarket-fake-bets-creators-influencers-us-users-062226),
[TechTimes/CFTC](https://www.techtimes.com/articles/319716/20260704/polymarket-paid-creators-fake-bets-140-million-view-campaign-cftc-investigates.htm),
[City Journal](https://www.city-journal.org/article/prediction-market-ads-polymarket-kalshi),
[NPR](https://www.npr.org/2026/06/07/nx-s1-5846806/kalshi-polymarket-influencers-california-election)

Also note a widely circulated statistic — *"small accounts under $1k averaged
62× returns"* — is a **survivorship artifact**. It is an unweighted mean of
ratios across surviving wallets: a $12 wallet reaching $600 registers as 50×,
while every zeroed wallet exits the sample. The number is meaningless.

The most likely explanations for a second-hand $300k story, in order: a much
larger capital base than implied; a single concentrated bet that happened to
win (with the equally-sized population who lost going unmentioned); a partial
account that omits prior losses; or marketing content. None of these is a
process you can buy or copy.

---

## 6. The market got harder, not easier

- Institutional bid-ask spreads compressed from **~10% in the early 2020s to
  under 0.5% today**.
- Susquehanna and DRW run dedicated event-contract desks; DRW pays ~$200k base
  salaries for the seats. SIG recruits explicitly to "detect incorrect fair
  values."
- Intra-market arbitrage windows now average **~2.7 seconds**.

The retail edge that existed in 2020 was the 10% spread. It is gone.

---

## 7. The three honest paths

### More capital — the only reliable one

Returns scale with capital; risk-per-dollar does not change. At the 1–4%/month
that constraint arbitrage plausibly supports:

| Capital | Realistic monthly |
|---|---|
| $5,000 | $50–100 unconditional; $150–400 if the edge is real |
| $30,000 | $1,200–2,700 if the edge is real |
| $100,000 | $1,000–4,000 |

The research's composite estimate for a competent new entrant on $5,000:
**$50–$100/month unconditionally, with a 35–50% chance the year ends
negative**; $150–$400/month conditional on the edges being real and sizing
being disciplined.

**$1,000/month is roughly a $50,000–$100,000 problem, not a strategy problem.**
The system already built scales to that without modification — Kalshi's
position-accountability cap is $25,000 per strike, well above what a $5k
account can use.

### The fee curve is the real edge, and it reorders everything

The most actionable single fact in the research. Kalshi's fee is parabolic in
price, so the **break-even forecasting edge** — how much you must out-predict
the market by before earning a cent — varies enormously:

| Price | Fee/contract | Break-even edge |
|---|---|---|
| 50c | 1.75c | **1.75 pp** |
| 80c | 1.12c | 1.12 pp |
| 90c | 0.63c | 0.63 pp |
| 95c | 0.33c | 0.33 pp |
| **97c** | **0.20c** | **0.20 pp** |
| 99c | 0.07c | 0.07 pp |

**The same forecasting skill is worth about nine times more at 97c than at
50c.** At mid-book you must beat a market that already aggregates public
forecasts by 1.75 percentage points; at 97c, by 0.20. As a maker, divide by
four again.

`WeatherEdgeStrategy` derives its trade threshold from the fee at the actual
price rather than using a flat cents figure, so it automatically hunts where
the hurdle is lowest. A flat threshold does the opposite: it admits mid-book
trades needing a huge edge and rejects wing trades needing almost none.

### The one documented live record

The best publicly documented Kalshi weather trading record: **1,038 settled
trades, real money, Feb–Jul 2026, netting +$1,817 after fees — about
$415/month** on only ~$102/day of deployed capital.

The honest reading of that record matters as much as the headline. Monthly
path: Feb +$116, Mar +$7, Apr −$377, May +$56, **Jun +$986, Jul +$1,030**.
Feb–May was cumulatively **−$198 across 816 trades**. Over 100% of lifetime
profit arrived in the final two months, after a model change, during summer —
when temperature distributions are tightest and most predictable.

Correcting the significance test for spatial correlation (same-day forecast
errors cluster at ~1,000km synoptic scale, so ~1,038 trades is really ~130–200
independent observations) gives **t ≈ 1.5–2.1, p ≈ 0.04–0.13. Suggestive, not
established.** A pure seasonality explanation for the whole record is still
alive and only a 12-month sample spanning a shoulder season can rule it out.

### A warning about the intraday trade specifically

Interactive Brokers measured a comparable prediction market against NWS LAMP
guidance across 23 cities: **the market beat LAMP in 20 of 23, median +17.2%,
with its advantage widening to ~40% in the hours before the daily high.** The
market is sharpest exactly when the intraday lock-in trade fires. That does not
kill the idea — settled is settled — but it means the mispricing must come from
the venue lagging *observations*, not from out-forecasting the market.

### More edge — the only one that compounds skill

This is what the Odd Lots sharps do: pick one domain, build genuinely better
information than the market, and work it. The cheapest such edge available here
is **weather**, because it is the only strategy in this system that can be
tested *today* — station observations go back decades, so forecast skill and
the intraday certainty effect can both be measured before any capital or
waiting is committed.

Run `orbit weather-study`. It answers, per station and hour, what fraction of
days had already hit their maximum by that hour. If that curve is steep and
early, there is a real, repeatable, latency-tolerant edge and it is worth
pursuing hard. If it is flat and late, the idea is dead and you have lost one
command instead of a month.

Note what the study cannot tell you: whether the market has *already priced*
that certainty. That needs recorded prices, which is what `orbit record` is for.

### More risk — works sometimes, ruins accounts often

There is no leverage on these venues (positions are fully collateralised), so
the only way to amplify is concentration. Concentration is exactly what
produced both Théo's $85M and beachboy4's −$2M with a 51% win rate.

If you want the honest version: targeting 20%/month with concentrated
directional bets gives you a real chance of hitting it in any given month, and
a substantially larger cumulative chance of losing most of the account within a
year. The distribution has a fat right tail *and* a fat left tail, and the
left tail is where 70% of accounts actually land.

---

## 8. What I would actually do

1. **Run `orbit weather-study` today.** One command, no capital, no waiting.
   It is the single highest-information action available.
2. **Run `orbit record` continuously** regardless of what you decide. The
   archive is the only asset here that cannot be bought later.
3. **Paper trade for the full gate period.** Watch fill rate more than PnL.
4. **If the weather curve is steep and paper trading shows real fills**, that is
   genuine evidence of an edge — and the correct response is to add capital,
   because the strategy has capacity far above $5,000.
5. **If neither shows an edge**, the correct response is to stop. That is a
   real outcome and the base rates say it is the likely one.

The thing I would not do is size up to chase 20%/month on an unproven edge.
That converts a system with a small positive expectation into the beachboy4
outcome.

---

## 9. What would make this analysis wrong

Specific, testable findings that would justify real optimism:

- **The weather certainty curve is steep and early** (say >70% of days settled
  by 3pm local) **and** recorded Kalshi prices show those settled contracts
  trading meaningfully away from 0/100. That is a genuine repeatable edge.
- **Constraint violations turn out frequent and fillable** — a fill rate above
  50% on detected violations would mean the archive-based estimate was too
  conservative.
- **Kalshi's maker fee is genuinely $0 on liquid series** and quoting captures
  spread without adverse selection, which would make market making viable at a
  capital level far below what the research assumed.

Each is measurable within 30–60 days with the system as built. None requires
believing anything on faith.
