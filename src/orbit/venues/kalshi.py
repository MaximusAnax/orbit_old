"""Kalshi adapter.

Contract details verified against the official ``kalshi-python`` 2.1.0 client
source (the generated OpenAPI client is a more reliable spec than the prose
docs). Anything that could not be verified offline is listed in
``docs/venue-verification.md`` and must be confirmed against the demo
environment before live trading.

Venue facts that shape this module:

* Base URL ``https://api.elections.kalshi.com/trade-api/v2``; a full demo
  environment exists at ``https://demo-api.elections.kalshi.com/trade-api/v2``
  with identical semantics. Paper trading runs there, against real API
  behaviour rather than a simulator we wrote ourselves.
* Auth is an RSA-PSS signature over ``timestamp_ms + METHOD + path``, not a
  bearer token. The timestamp is part of the signed payload, so **clock skew
  breaks authentication** — hence the skew check in :meth:`KalshiAdapter.ping`.
* Prices are integer cents constrained to ``1..99``. There is no sub-cent tick
  and no trading at 0 or 100.
* The order book publishes **bids on both sides** (YES bids and NO bids) with
  no explicit asks; see :func:`orbit.venues.base.normalize_binary_book`.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import time
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from typing import Any

import aiohttp
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from orbit.core.money import (
    PIPS_PER_CENT,
    PIPS_PER_DOLLAR,
    cents_to_pips,
    pips_to_cents,
)
from orbit.core.types import (
    Balance,
    Fill,
    Market,
    MarketStatus,
    Order,
    OrderBook,
    OrderRequest,
    OrderStatus,
    OrderType,
    Position,
    Side,
    TimeInForce,
    Trade,
    Venue,
)
from orbit.venues.base import (
    AuthError,
    InsufficientFundsError,
    OrderRejectedError,
    RateLimitError,
    VenueAdapter,
    VenueCapabilities,
    VenueError,
    normalize_binary_book,
)

PROD_BASE = "https://api.elections.kalshi.com/trade-api/v2"
DEMO_BASE = "https://demo-api.elections.kalshi.com/trade-api/v2"
PROD_WS = "wss://api.elections.kalshi.com/trade-api/ws/v2"
DEMO_WS = "wss://demo-api.elections.kalshi.com/trade-api/ws/v2"

#: Kalshi rejects requests whose signed timestamp is too far from server time.
#: We refuse to trade past this skew rather than emit a storm of auth failures.
MAX_CLOCK_SKEW_S = 5.0

_STATUS_MAP = {
    "active": MarketStatus.ACTIVE,
    "open": MarketStatus.ACTIVE,
    "initialized": MarketStatus.PAUSED,
    "paused": MarketStatus.PAUSED,
    "closed": MarketStatus.CLOSED,
    "determined": MarketStatus.CLOSED,
    "finalized": MarketStatus.SETTLED,
    "settled": MarketStatus.SETTLED,
}


class KalshiSigner:
    """RSA-PSS request signer.

    Kalshi signs ``timestamp + METHOD + path`` where ``path`` excludes the
    query string. Salt length is the digest length (not the more common
    "max length"), which is the detail that most third-party implementations
    get wrong and then debug for an afternoon.
    """

    def __init__(self, key_id: str, private_key_pem: bytes) -> None:
        self.key_id = key_id
        key = serialization.load_pem_private_key(private_key_pem, password=None)
        if not isinstance(key, rsa.RSAPrivateKey):
            raise AuthError(
                "Kalshi requires an RSA private key", venue=Venue.KALSHI.value
            )
        self._key = key

    @classmethod
    def from_file(cls, key_id: str, path: str) -> KalshiSigner:
        with open(path, "rb") as fh:
            return cls(key_id, fh.read())

    def headers(self, method: str, path: str) -> dict[str, str]:
        timestamp = str(int(time.time() * 1000))
        message = f"{timestamp}{method.upper()}{path}".encode()
        signature = self._key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
        return {
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode(),
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value, tz=UTC)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_market(raw: dict[str, Any]) -> Market:
    """Translate a Kalshi market payload into the shared :class:`Market`."""
    ticker = str(raw.get("ticker", ""))
    tick_cents = raw.get("tick_size") or 1
    return Market(
        venue=Venue.KALSHI,
        venue_id=ticker,
        title=str(raw.get("title") or raw.get("subtitle") or ticker),
        event_key=str(raw.get("event_ticker") or ticker),
        status=_STATUS_MAP.get(str(raw.get("status", "")).lower(), MarketStatus.UNKNOWN),
        tick_pips=int(tick_cents) * PIPS_PER_CENT,
        close_time=_parse_ts(raw.get("close_time")),
        expected_settle_time=_parse_ts(raw.get("expiration_time")),
        meta={
            k: str(raw[k])
            for k in ("series_ticker", "market_type", "result", "can_close_early")
            if raw.get(k) is not None
        },
    )


def parse_orderbook(
    market_key: str, raw: dict[str, Any], *, depth: int | None = None
) -> OrderBook:
    """Translate Kalshi's dual-bid book into a YES-space book.

    Kalshi returns ``{"yes": [[price_cents, count], ...], "no": [...]}`` where
    *both* arrays are bids. Some client versions alias these to
    ``"true"``/``"false"``; both spellings are accepted here.
    """
    book = raw.get("orderbook", raw) or {}
    yes_raw = book.get("yes") or book.get("true") or []
    no_raw = book.get("no") or book.get("false") or []

    def levels(rows: Any) -> list[tuple[int, int]]:
        out: list[tuple[int, int]] = []
        for row in rows or []:
            if isinstance(row, dict):
                price, count = row.get("price"), row.get("count")
            elif isinstance(row, list | tuple) and len(row) >= 2:
                price, count = row[0], row[1]
            else:
                continue
            if price is None or count is None:
                continue
            out.append((cents_to_pips(int(price)), int(count)))
        return out

    return normalize_binary_book(
        market_key=market_key,
        timestamp=datetime.now(UTC),
        yes_bids=levels(yes_raw),
        no_bids=levels(no_raw),
        depth=depth,
    )


class KalshiAdapter(VenueAdapter):
    """Async Kalshi client covering market data, trading and account state."""

    venue = Venue.KALSHI
    capabilities = VenueCapabilities(
        supports_post_only=False,  # no post-only flag in the v2 order schema
        supports_batch_orders=True,  # POST /portfolio/orders/batched
        supports_order_amend=True,  # POST /portfolio/orders/{id}/amend
        nets_multi_outcome_margin=True,  # mutually exclusive groups net collateral
        supports_split_merge=False,
        min_order_size=1,
        max_order_size=None,
        typical_latency_ms=150,
    )

    def __init__(
        self,
        signer: KalshiSigner | None = None,
        *,
        demo: bool = True,
        session: aiohttp.ClientSession | None = None,
        timeout_s: float = 10.0,
    ) -> None:
        self.base = DEMO_BASE if demo else PROD_BASE
        self.ws_url = DEMO_WS if demo else PROD_WS
        self.demo = demo
        self._signer = signer
        self._session = session
        self._owns_session = session is None
        self._timeout = aiohttp.ClientTimeout(total=timeout_s)
        self._ws_seq: dict[str, int] = {}

    # -- plumbing -----------------------------------------------------------

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
            self._owns_session = True
        return self._session

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        auth: bool = True,
    ) -> dict[str, Any]:
        """Issue one signed request, mapping venue errors onto our taxonomy."""
        session = await self._get_session()
        # The signature covers the path *including* the /trade-api/v2 prefix
        # but excluding the query string.
        sign_path = self.base.split(".com", 1)[-1] + path
        headers: dict[str, str] = {"Accept": "application/json"}
        if auth:
            if self._signer is None:
                raise AuthError(
                    "Kalshi credentials required for this call",
                    venue=self.venue.value,
                )
            headers = self._signer.headers(method, sign_path)

        async with session.request(
            method,
            f"{self.base}{path}",
            params=params,
            json=body,
            headers=headers,
        ) as resp:
            text = await resp.text()
            if resp.status == 429:
                raise RateLimitError(
                    "Kalshi rate limit",
                    venue=self.venue.value,
                    retry_after_s=float(resp.headers.get("Retry-After", 1)),
                )
            if resp.status in (401, 403):
                raise AuthError(f"Kalshi auth failed: {text}", venue=self.venue.value)
            if resp.status >= 400:
                lowered = text.lower()
                if "insufficient" in lowered or "balance" in lowered:
                    raise InsufficientFundsError(text, venue=self.venue.value)
                raise VenueError(
                    f"Kalshi {method} {path} -> {resp.status}: {text}",
                    venue=self.venue.value,
                    retryable=resp.status >= 500,
                )
            return json.loads(text) if text else {}

    async def clock_skew_s(self) -> float:
        """Measure our clock against the exchange's, in seconds.

        The auth signature covers a millisecond timestamp, so a drifting
        container clock shows up as blanket 401s that look like bad
        credentials. Reading the server's ``Date`` header turns that
        misdiagnosis into a number. Positive means we are ahead.
        """
        session = await self._get_session()
        async with session.get(f"{self.base}/exchange/status") as resp:
            server_date = resp.headers.get("Date")
            local = time.time()
        if not server_date:
            return 0.0
        try:
            from email.utils import parsedate_to_datetime

            server = parsedate_to_datetime(server_date).timestamp()
        except (TypeError, ValueError):
            return 0.0
        return local - server

    async def assert_clock_sane(self) -> None:
        """Refuse to trade on a badly skewed clock."""
        skew = await self.clock_skew_s()
        if abs(skew) > MAX_CLOCK_SKEW_S:
            raise AuthError(
                f"clock skew {skew:+.1f}s exceeds {MAX_CLOCK_SKEW_S}s; "
                "Kalshi will reject signed requests — sync NTP before trading",
                venue=self.venue.value,
            )

    # -- reference data -----------------------------------------------------

    async def list_markets(
        self, *, status: str | None = "open", limit: int = 200
    ) -> list[Market]:
        params: dict[str, Any] = {"limit": min(limit, 1000)}
        if status:
            params["status"] = status
        markets: list[Market] = []
        cursor: str | None = None
        while len(markets) < limit:
            if cursor:
                params["cursor"] = cursor
            payload = await self._request("GET", "/markets", params=params, auth=False)
            batch = payload.get("markets") or []
            if not batch:
                break
            markets.extend(parse_market(m) for m in batch)
            cursor = payload.get("cursor")
            if not cursor:
                break
        return markets[:limit]

    async def get_market(self, venue_id: str) -> Market:
        payload = await self._request("GET", f"/markets/{venue_id}", auth=False)
        return parse_market(payload.get("market", payload))

    # -- market data --------------------------------------------------------

    async def get_book(self, venue_id: str, *, depth: int = 10) -> OrderBook:
        payload = await self._request(
            "GET", f"/markets/{venue_id}/orderbook", params={"depth": depth}, auth=False
        )
        return parse_orderbook(self.market_key(venue_id), payload, depth=depth)

    async def stream_books(
        self, venue_ids: Sequence[str]
    ) -> AsyncIterator[OrderBook]:
        """Stream book snapshots/deltas over the v2 websocket.

        Kalshi sends an ``orderbook_snapshot`` followed by ``orderbook_delta``
        messages carrying a monotonically increasing ``seq``. A gap means we
        missed a message and the local book is now wrong; the only safe
        response is to resubscribe rather than keep trading a corrupt book.
        """
        if self._signer is None:
            raise AuthError("websocket requires credentials", venue=self.venue.value)
        session = await self._get_session()
        sign_path = self.ws_url.split(".com", 1)[-1]
        books: dict[str, dict[str, dict[int, int]]] = {}

        async with session.ws_connect(
            self.ws_url, headers=self._signer.headers("GET", sign_path)
        ) as ws:
            await ws.send_json(
                {
                    "id": 1,
                    "cmd": "subscribe",
                    "params": {
                        "channels": ["orderbook_delta"],
                        "market_tickers": list(venue_ids),
                    },
                }
            )
            async for msg in ws:
                if msg.type is not aiohttp.WSMsgType.TEXT:
                    continue
                data = json.loads(msg.data)
                kind = data.get("type")
                payload = data.get("msg") or {}
                ticker = payload.get("market_ticker")
                if not ticker or kind not in (
                    "orderbook_snapshot",
                    "orderbook_delta",
                ):
                    continue
                key = self.market_key(ticker)

                if kind == "orderbook_snapshot":
                    books[ticker] = {
                        "yes": {
                            int(p): int(c) for p, c in (payload.get("yes") or [])
                        },
                        "no": {int(p): int(c) for p, c in (payload.get("no") or [])},
                    }
                else:
                    state = books.get(ticker)
                    if state is None:
                        continue  # delta before snapshot; wait for one
                    side = payload.get("side")
                    price, delta = payload.get("price"), payload.get("delta")
                    if side not in state or price is None or delta is None:
                        continue
                    level = state[side].get(int(price), 0) + int(delta)
                    if level > 0:
                        state[side][int(price)] = level
                    else:
                        state[side].pop(int(price), None)

                state = books[ticker]
                yield normalize_binary_book(
                    market_key=key,
                    timestamp=datetime.now(UTC),
                    yes_bids=[
                        (cents_to_pips(p), c) for p, c in state["yes"].items() if c > 0
                    ],
                    no_bids=[
                        (cents_to_pips(p), c) for p, c in state["no"].items() if c > 0
                    ],
                    sequence=data.get("seq"),
                )

    async def get_trades(self, venue_id: str, *, limit: int = 100) -> list[Trade]:
        payload = await self._request(
            "GET",
            "/markets/trades",
            params={"ticker": venue_id, "limit": limit},
            auth=False,
        )
        out: list[Trade] = []
        for row in payload.get("trades") or []:
            price = row.get("yes_price")
            if price is None:
                continue
            taker = row.get("taker_side")
            out.append(
                Trade(
                    market_key=self.market_key(venue_id),
                    timestamp=_parse_ts(row.get("created_time")) or datetime.now(UTC),
                    price_pips=cents_to_pips(int(price)),
                    size=int(row.get("count") or 0),
                    taker_side=(
                        Side.BUY
                        if taker == "yes"
                        else Side.SELL
                        if taker == "no"
                        else None
                    ),
                )
            )
        return out

    # -- trading ------------------------------------------------------------

    def _order_payload(self, request: OrderRequest) -> dict[str, Any]:
        """Map a YES-space :class:`OrderRequest` onto Kalshi's schema.

        We always trade the ``yes`` side and express direction through
        ``action``. Kalshi's alternative encoding — buying NO at the
        complement — is economically identical but makes reconciliation
        harder, because fills come back on a different side than the strategy
        reasoned about.
        """
        ticker = request.market_key.split(":", 1)[1]
        payload: dict[str, Any] = {
            "ticker": ticker,
            "client_order_id": request.client_order_id,
            "side": "yes",
            "action": "buy" if request.side is Side.BUY else "sell",
            "count": request.size,
            "type": "limit" if request.order_type is OrderType.LIMIT else "market",
        }
        if request.price_pips is not None:
            cents = round(pips_to_cents(request.price_pips))
            payload["yes_price"] = max(1, min(99, cents))
        if request.time_in_force is TimeInForce.IOC:
            # Kalshi expresses immediate-or-cancel as an immediate expiry.
            payload["expiration_ts"] = int(time.time())
        return payload

    async def place_order(self, request: OrderRequest) -> Order:
        order = Order(request=request)
        try:
            payload = await self._request(
                "POST", "/portfolio/orders", body=self._order_payload(request)
            )
        except OrderRejectedError as exc:
            return order.with_status(OrderStatus.REJECTED, reason=str(exc))
        raw = payload.get("order", payload)
        order.venue_order_id = raw.get("order_id")
        order.status = self._map_order_status(raw.get("status"))
        filled = int(raw.get("taker_fill_count") or 0)
        if filled:
            order.filled_size = filled
            price = raw.get("taker_fill_cost")
            if price:
                order.avg_fill_pips = cents_to_pips(int(price)) // max(1, filled)
        return order

    @staticmethod
    def _map_order_status(raw: Any) -> OrderStatus:
        return {
            "resting": OrderStatus.OPEN,
            "open": OrderStatus.OPEN,
            "pending": OrderStatus.PENDING,
            "executed": OrderStatus.FILLED,
            "filled": OrderStatus.FILLED,
            "canceled": OrderStatus.CANCELED,
            "cancelled": OrderStatus.CANCELED,
            "rejected": OrderStatus.REJECTED,
            "expired": OrderStatus.EXPIRED,
        }.get(str(raw).lower(), OrderStatus.OPEN)

    async def cancel_order(self, order: Order) -> Order:
        if not order.venue_order_id:
            return order.with_status(OrderStatus.CANCELED, reason="never acknowledged")
        with contextlib.suppress(VenueError):
            await self._request(
                "DELETE", f"/portfolio/orders/{order.venue_order_id}"
            )
        return order.with_status(OrderStatus.CANCELED)

    async def cancel_all(self) -> int:
        """Cancel every resting order. The kill switch depends on this."""
        orders = await self.get_open_orders()
        results = await asyncio.gather(
            *(self.cancel_order(o) for o in orders), return_exceptions=True
        )
        return sum(1 for r in results if not isinstance(r, BaseException))

    async def get_open_orders(self) -> list[Order]:
        payload = await self._request(
            "GET", "/portfolio/orders", params={"status": "resting"}
        )
        out: list[Order] = []
        for raw in payload.get("orders") or []:
            ticker = raw.get("ticker")
            price = raw.get("yes_price")
            if not ticker or price is None:
                continue
            action = str(raw.get("action", "buy"))
            req = OrderRequest(
                market_key=self.market_key(ticker),
                side=Side.BUY if action == "buy" else Side.SELL,
                size=int(raw.get("initial_count") or raw.get("count") or 0) or 1,
                price_pips=cents_to_pips(int(price)),
                client_order_id=str(raw.get("client_order_id") or raw.get("order_id")),
            )
            order = Order(request=req, venue_order_id=raw.get("order_id"))
            order.status = self._map_order_status(raw.get("status"))
            order.filled_size = int(raw.get("taker_fill_count") or 0)
            out.append(order)
        return out

    async def get_fills(self, *, since: datetime | None = None) -> list[Fill]:
        params: dict[str, Any] = {"limit": 200}
        if since:
            params["min_ts"] = int(since.timestamp())
        payload = await self._request("GET", "/portfolio/fills", params=params)
        out: list[Fill] = []
        for raw in payload.get("fills") or []:
            ticker = raw.get("ticker")
            price = raw.get("yes_price")
            if not ticker or price is None:
                continue
            is_taker = bool(raw.get("is_taker"))
            action = str(raw.get("action", "buy"))
            out.append(
                Fill(
                    market_key=self.market_key(ticker),
                    timestamp=_parse_ts(raw.get("created_time")) or datetime.now(UTC),
                    side=Side.BUY if action == "buy" else Side.SELL,
                    size=int(raw.get("count") or 0),
                    price_pips=cents_to_pips(int(price)),
                    # Kalshi reports fees per fill in cents when present.
                    fee_pips=cents_to_pips(int(raw.get("fee") or 0)),
                    liquidity="taker" if is_taker else "maker",
                    order_id=str(raw.get("order_id") or ""),
                    client_order_id=str(raw.get("client_order_id") or ""),
                    venue_fill_id=str(raw.get("trade_id") or "") or None,
                )
            )
        return out

    # -- account ------------------------------------------------------------

    async def get_balance(self) -> Balance:
        payload = await self._request("GET", "/portfolio/balance")
        # Kalshi reports balance in cents.
        return Balance(
            venue=self.venue,
            cash_pips=cents_to_pips(int(payload.get("balance") or 0)),
        )

    async def get_positions(self) -> list[Position]:
        payload = await self._request(
            "GET", "/portfolio/positions", params={"count_filter": "position"}
        )
        out: list[Position] = []
        for raw in payload.get("market_positions") or []:
            ticker = raw.get("ticker")
            if not ticker:
                continue
            size = int(raw.get("position") or 0)
            if size == 0:
                continue
            pos = Position(market_key=self.market_key(ticker), size=size)
            # ``market_exposure`` is collateral committed, in cents, always
            # positive. For a long that *is* the cost basis. For a short, the
            # collateral is the complement of the entry price, so the basis is
            # recovered as exposure - $1 * |size| — e.g. 100 short at 40c locks
            # $60 of collateral and carries a basis of -$40.
            exposure_pips = cents_to_pips(int(raw.get("market_exposure") or 0))
            pos.cost_basis_pips = (
                exposure_pips
                if size > 0
                else exposure_pips - PIPS_PER_DOLLAR * abs(size)
            )
            pos.realized_pnl_pips = cents_to_pips(int(raw.get("realized_pnl") or 0))
            pos.fees_paid_pips = cents_to_pips(int(raw.get("fees_paid") or 0))
            out.append(pos)
        return out

    async def close(self) -> None:
        if self._session and self._owns_session and not self._session.closed:
            await self._session.close()
