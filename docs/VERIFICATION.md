# Pre-live verification checklist

Orbit was built in an environment where **the venue APIs were unreachable** —
`kalshi.com`, `clob.polymarket.com` and their documentation hosts were blocked
by network egress policy. API contracts were therefore derived from the
official SDK sources (`kalshi-python` 2.1.0, `py-clob-client`), which are
generated from the same specifications and are more reliable than prose docs,
but **nothing below has been executed against a live venue**.

Every item here must be confirmed before real money is at risk. Kalshi's demo
environment (`demo-api.elections.kalshi.com`) has identical semantics and is
the right place to do it.

Treat an unchecked box as a known unknown, not as a detail.

---

## Kalshi

### Authentication
- [ ] RSA-PSS signature with `salt_length = DIGEST_LENGTH` is accepted.
      (`MGF1(SHA256)`, message = `timestamp_ms + METHOD + path`, path excluding
      the query string.) Salt length is the most common implementation error.
- [ ] `clock_skew_s()` returns a small value; the `Date` header is present.
- [ ] Signing path includes the `/trade-api/v2` prefix.

### Order book
- [ ] `GET /markets/{ticker}/orderbook` returns `yes` and `no` arrays that are
      **both bids**, with no explicit asks.
- [ ] Confirm the JSON key spelling: `yes`/`no` versus `true`/`false`. The
      parser accepts both, but confirm which is live.
- [ ] Level shape: `[price_cents, count]` pairs versus `{price, count}` objects.
- [ ] A NO bid at `p` really is a YES offer at `100 − p` for order placement.
      **If this is wrong, every book in the system is inverted.**

### Orders
- [ ] `side="yes"` with `action="sell"` opens a short when flat, rather than
      being rejected for lack of inventory. If it *is* rejected, the adapter
      must switch to `side="no", action="buy"` at the complement price —
      see `_order_payload` in `orbit/venues/kalshi.py`.
- [ ] `client_order_id` is honoured for idempotency.
- [ ] IOC via `expiration_ts` behaves as immediate-or-cancel.
- [ ] Position limits per market, and whether they bind at this size.

### Fees — the numbers every strategy depends on
- [ ] Taker rate is still `0.07` on the series you trade.
- [ ] Maker is genuinely free on those series. Research indicates ~149 of
      12,199 series carry a maker fee; confirm yours is not one.
- [ ] **The cent ceiling applies per fill, not per order.** Place an order that
      fills across several resting orders and compare the total fee to
      `KalshiFees.trade_fee_pips(..., n_fills=N)`. This materially changes
      profitability on thin books.
- [ ] Settlement fees are zero on your series.

### Positions
- [ ] `market_exposure` is collateral in cents, and short basis recovers as
      `exposure − $1 × |size|`. Verify with one small short.
- [ ] `GET /portfolio/fills` reports `fee` in cents and `is_taker` correctly.

---

## Polymarket

- [ ] `funder` is the **proxy wallet** holding USDC, not the EOA derived from
      the private key. Getting this wrong produces orders that sign correctly
      and then fail on collateral.
- [ ] `signature_type` matches the account (1 = proxy, 0 = EOA, 2 = Gnosis Safe).
- [ ] Trading fees are still zero on the markets you trade (`GET /fee-rate`).
- [ ] `post_only` is accepted and genuinely rejects marketable orders.
- [ ] `/book` bid/ask ordering matches what `parse_clob_book` assumes.
- [ ] Order sizes: minimum notional, and whether whole-share rounding is
      acceptable (Orbit rounds down).
- [ ] `GET /neg-risk` correctly identifies multi-outcome markets.
- [ ] Balance decimals: USDC is 6dp; confirm `get_balance` returns dollars.

---

## Strategy-level verification

- [ ] **Strike parsing.** Run `orbit scan` and inspect the discovered ladders.
      Confirm that `-T`/`-B` suffixes mean threshold/bucket on the series you
      trade, and that higher strike really is the less likely event. A reversed
      convention inverts the arbitrage direction.
- [ ] **Partition exhaustiveness.** Inferred partitions are disabled by default
      and must stay that way until you have confirmed, per event, that the
      listed markets are mutually exclusive *and* exhaustive. Scanning for
      `ΣYES < $1` on a non-exhaustive set is the most expensive beginner error
      in this space.
- [ ] **Cross-venue pairs.** `resolution_verified` defaults to `False` and must
      only be set after reading *both* rulebooks. Resolution-criteria divergence
      is the dominant risk, not the price gap: Kalshi resolves internally,
      Polymarket Global resolves via the UMA optimistic oracle, and Polymarket
      US resolves via its own markets team. Different sources, different dates,
      different edge cases.
- [ ] **Fill rate.** Watch it during paper trading. A high detection rate with a
      low fill rate means the violations are stale quotes rather than tradable
      edges — which is exactly what the promotion gate is designed to block.

---

## Operational

- [ ] NTP is running. Kalshi signature auth fails on clock drift, presenting as
      inexplicable 401s.
- [ ] Kill switch works: `POST /api/kill` halts trading and cancels orders.
- [ ] Reconciliation is clean: local positions match the venue.
- [ ] Alerts deliver — send a test before trusting them.
- [ ] Recorder has been running long enough to backtest on.
- [ ] Disk has room; tick data grows steadily.
