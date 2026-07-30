# Runbook

Operating Orbit: daily checks, incidents, and the go-live sequence.

---

## Deployment order

Deploy in this order, and do not compress it. Each step exists to make the next
one safe.

1. **Recorder only**, for at least two weeks. It cannot place an order, so the
   risk is zero and the archive it builds is a prerequisite for everything else.
   There is no public order-book history for these venues; if you skip this,
   you have nothing to backtest against, ever.
2. **`orbit scan`**, occasionally. Confirms the constraint discovery is
   producing sensible relationships on real tickers. Read the output — you are
   checking that ladders make sense, not looking for profit.
3. **Backtest** against the archive. Look at the fill rate as hard as the PnL.
4. **Paper trade**, at least two weeks, until the promotion gate clears.
5. **Live with a fraction of capital.** Not all of it, and not on day one.

---

## Daily checks

Two minutes on the dashboard:

- **Kill switch** — not tripped. If it is, find out why before resetting.
- **Fill rate** — the single most informative number. Falling fill rate means
  detected violations are stale quotes rather than tradable edges.
- **Drawdown gauge** — how close to the automatic halt.
- **Recorder health** — `seconds_since_data` small, `is_stale` false. A
  connected-but-silent feed is the failure mode that quietly ruins an archive.
- **Daily summary** — if it did not arrive, the *process* is down. Silence is
  never good news.

Weekly:

- Reconcile positions (`/api/positions` against the venue's own UI).
- Check disk usage; tick data grows steadily.
- Re-read `docs/VERIFICATION.md` for anything still unchecked.

---

## Incidents

### Kill switch tripped

It is one-way by design. Do not reset it reflexively.

1. Read `kill_switch.reason` on the dashboard.
2. If **drawdown** or **daily loss**: stop. Something is losing money
   systematically. Review the trade log before resuming; the limit did its job.
3. If **manual**: whoever tripped it knows why.
4. Reset via `POST /api/resume?acknowledged_by=<your name>`. The name is
   recorded in the log.

### Position mismatch (reconciliation failed)

The most serious alert in the system. Local state disagreeing with the venue is
the precondition for every large unexplained loss.

1. Halt trading immediately: `POST /api/kill`.
2. Compare `/api/positions` with the venue UI.
3. The **venue is authoritative**, always.
4. Do not resume until they agree.

Usual causes: a fill arriving after a restart, a partially-unwound multi-leg
trade, or a manual trade placed outside the system.

### Partial multi-leg execution

Expected occasionally; handled automatically. The executor unwinds the filled
leg and logs `arb.partial_execution_unwound`. Unwinding loses the spread — that
is the correct trade, because an unintended directional position carried to
settlement is far worse.

If it happens *frequently*, the opportunities are not real. Raise
`ORBIT_MIN_PROFIT_CENTS` or stop trading that constraint family.

### Venue unreachable

The recorder retries with jittered backoff and one venue failing never affects
the other. No action unless it persists beyond ~30 minutes, in which case check
the venue's status page and your credentials.

### Kalshi returns 401 on everything

Almost always **clock drift**, not bad credentials — the auth signature covers a
millisecond timestamp. Check NTP, then `clock_skew_s()`. Orbit refuses to start
beyond 5 seconds of skew for this reason.

### Disk full

Tick data grows. Old Parquet partitions can be moved to cold storage; the
archive is date-partitioned so `data/books/venue=*/date=YYYY-MM-DD/` moves
cleanly. Never delete without archiving — it cannot be regenerated.

---

## Moving money

Deliberately manual. The system reports, you act.

### Depositing

1. Fund on the venue (Kalshi: ACH/wire. Polymarket: USDC.e on Polygon to your
   funder address).
2. Confirm the balance appears on the dashboard.
3. Update `ORBIT_BANKROLL_USD` and restart, so risk limits scale to the new
   capital. Limits are fractions of bankroll; a stale value means wrong limits.

### Withdrawing

1. **Halt trading first** (`POST /api/kill`), so nothing opens a position
   against capital you are removing.
2. Wait for open positions to settle, or close them manually. Collateral is
   locked until settlement — this is not optional and can take weeks on
   long-dated markets.
3. Withdraw on the venue's site.
4. Lower `ORBIT_BANKROLL_USD`, restart, then resume.

---

## Go-live checklist

Do not skip any of these.

- [ ] `docs/VERIFICATION.md` fully checked against the demo environment
- [ ] Recorder has ≥14 days of continuous data
- [ ] Backtest run and reviewed, fill rate understood
- [ ] Paper traded ≥14 days
- [ ] Promotion gate clears: `orbit status` shows `ready_for_live: true`
- [ ] `ORBIT_API_TOKEN` set to a strong random value
- [ ] Alerts tested end to end — send yourself a real one
- [ ] Kill switch tested from the dashboard
- [ ] `ORBIT_BANKROLL_USD` set to the amount you are **actually** deploying,
      which should be a fraction of your total capital
- [ ] Risk limits reviewed; tighter than you think you need
- [ ] You have read the "Read this before anything else" section of the README
      and accept that the realistic outcome distribution includes "this finds
      nothing fillable and correctly declines to trade"

---

## Useful commands

```bash
orbit config                     # effective configuration, no secrets
orbit status                     # query a running instance
orbit scan --limit 500           # one-shot constraint scan
orbit backtest --days 30         # replay the archive
orbit record --stream            # websocket recording instead of polling

# Archive health
python -c "from orbit.data.store import TickStore; \
           import json; print(json.dumps(TickStore('data').stats(), indent=2))"

# Emergency halt without the dashboard
curl -XPOST -H "Authorization: Bearer $ORBIT_API_TOKEN" \
     "http://127.0.0.1:8080/api/kill?reason=manual"
```
