"""Polymarket adapter.

Contract details verified against ``py-clob-client`` source. The split of
responsibilities here is deliberate:

* **Read path is ours.** Book, price and market endpoints are public and
  unauthenticated, so they go through our own ``aiohttp`` layer — async,
  batched, and on the hot path for every strategy.
* **Write path delegates to the official client.** Placing an order requires
  an EIP-712 signature over the CTF Exchange order struct, with a domain
  separator, salt, nonce, expiry and a signature type that differs between an
  EOA and a Polymarket proxy wallet. Reimplementing that buys nothing and
  risks silently malformed signatures, so :class:`PolymarketAdapter` wraps
  ``ClobClient`` and runs its synchronous calls in a thread executor.

Venue facts that shape this module:

* Zero trading fees historically, and order placement is gasless — a relayer
  submits on your behalf. This is Polymarket's structural advantage over
  Kalshi and the reason cross-venue pricing is asymmetric.
* ``post_only`` is supported on order placement, so a quoting strategy can
  guarantee it earns the maker side. Kalshi's v2 order schema has no
  equivalent.
* YES and NO tokens can be minted and redeemed as a pair against 1 USDC
  (split/merge). That enforces a hard arbitrage bound: YES + NO can never
  trade meaningfully below $1 without a risk-free trade appearing.
* Prices are decimal strings. Sizes are decimal shares; Orbit uses integer
  shares and rounds *down* when placing, so an order never exceeds its
  intended size.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import aiohttp

from orbit.core.money import dollars_to_pips, pips_to_dollars
from orbit.core.types import (
    Balance,
    Fill,
    Market,
    MarketStatus,
    Order,
    OrderBook,
    OrderRequest,
    OrderStatus,
    Position,
    Side,
    TimeInForce,
    Trade,
    Venue,
)
from orbit.venues.base import (
    AuthError,
    RateLimitError,
    VenueAdapter,
    VenueCapabilities,
    VenueError,
    normalize_two_sided_book,
)

CLOB_HOST = "https://clob.polymarket.com"
GAMMA_HOST = "https://gamma-api.polymarket.com"
POLYGON_CHAIN_ID = 137
AMOY_CHAIN_ID = 80002

#: Polymarket proxy-wallet signature types, from the CTF Exchange.
SIG_TYPE_EOA = 0
SIG_TYPE_POLY_PROXY = 1
SIG_TYPE_POLY_GNOSIS_SAFE = 2


@dataclass(frozen=True, slots=True)
class PolymarketCredentials:
    """Everything needed to trade.

    ``funder`` is the address actually holding USDC. For accounts created
    through the Polymarket UI this is a *proxy wallet*, not the EOA derived
    from ``private_key`` — getting this wrong produces orders that sign
    correctly and then fail on collateral, which is a confusing way to lose an
    afternoon.
    """

    private_key: str
    api_key: str = ""
    api_secret: str = ""
    api_passphrase: str = ""
    funder: str = ""
    signature_type: int = SIG_TYPE_POLY_PROXY
    chain_id: int = POLYGON_CHAIN_ID

    @property
    def has_api_creds(self) -> bool:
        return bool(self.api_key and self.api_secret and self.api_passphrase)


def parse_gamma_market(raw: dict[str, Any]) -> list[Market]:
    """Translate one Gamma market into per-outcome :class:`Market` objects.

    A Polymarket "market" is a condition with N outcome tokens; Orbit's unit
    is a single binary claim, so a two-outcome market yields two entries that
    share an ``event_key``. Only the YES leg is normally traded, but the NO
    leg is kept because YES + NO parity is a tradable relationship.
    """
    import json as _json

    token_ids = raw.get("clobTokenIds")
    if isinstance(token_ids, str):
        with contextlib.suppress(ValueError):
            token_ids = _json.loads(token_ids)
    outcomes = raw.get("outcomes")
    if isinstance(outcomes, str):
        with contextlib.suppress(ValueError):
            outcomes = _json.loads(outcomes)
    if not isinstance(token_ids, list) or not token_ids:
        return []
    if not isinstance(outcomes, list) or len(outcomes) != len(token_ids):
        outcomes = [f"outcome{i}" for i in range(len(token_ids))]

    closed = bool(raw.get("closed"))
    active = bool(raw.get("active", True))
    status = (
        MarketStatus.SETTLED
        if closed
        else MarketStatus.ACTIVE
        if active
        else MarketStatus.PAUSED
    )
    condition_id = str(raw.get("conditionId") or raw.get("id") or "")
    question = str(raw.get("question") or raw.get("title") or condition_id)
    end = raw.get("endDate") or raw.get("end_date_iso")
    close_time: datetime | None = None
    if end:
        with contextlib.suppress(ValueError):
            close_time = datetime.fromisoformat(str(end).replace("Z", "+00:00"))

    tick = raw.get("orderPriceMinTickSize") or 0.01
    return [
        Market(
            venue=Venue.POLYMARKET,
            venue_id=str(token_id),
            title=f"{question} [{outcome}]",
            event_key=condition_id,
            status=status,
            tick_pips=max(1, dollars_to_pips(float(tick))),
            close_time=close_time,
            meta={
                "condition_id": condition_id,
                "outcome": str(outcome),
                "neg_risk": str(raw.get("negRisk", False)),
                "question": question,
            },
        )
        for token_id, outcome in zip(token_ids, outcomes, strict=False)
    ]


def parse_clob_book(market_key: str, raw: dict[str, Any]) -> OrderBook:
    """Translate a CLOB ``/book`` payload into a normalised book.

    Polymarket returns ``{"bids": [{"price": "0.52", "size": "100"}], ...}``
    with decimal strings, already per-outcome-token, so this is a parse and
    sort rather than a reflection.
    """

    def levels(rows: Any) -> list[tuple[int, int]]:
        out: list[tuple[int, int]] = []
        for row in rows or []:
            try:
                price = dollars_to_pips(float(row["price"]))
                size = int(float(row["size"]))
            except (KeyError, TypeError, ValueError):
                continue
            if size > 0:
                out.append((price, size))
        return out

    ts = raw.get("timestamp")
    timestamp = datetime.now(UTC)
    if ts:
        with contextlib.suppress(TypeError, ValueError, OSError):
            # Polymarket sends milliseconds.
            timestamp = datetime.fromtimestamp(int(ts) / 1000, tz=UTC)

    return normalize_two_sided_book(
        market_key=market_key,
        timestamp=timestamp,
        bids=levels(raw.get("bids")),
        asks=levels(raw.get("asks")),
    )


class PolymarketAdapter(VenueAdapter):
    """Async Polymarket CLOB client."""

    venue = Venue.POLYMARKET
    capabilities = VenueCapabilities(
        supports_post_only=True,  # post_order(..., post_only=True)
        supports_batch_orders=True,  # POST /orders
        supports_order_amend=False,  # cancel + replace only
        nets_multi_outcome_margin=True,  # neg-risk adapter for multi-outcome
        supports_split_merge=True,  # 1 USDC <-> YES + NO via the CTF
        min_order_size=5,  # venue enforces a small notional minimum
        max_order_size=None,
        typical_latency_ms=250,
    )

    def __init__(
        self,
        credentials: PolymarketCredentials | None = None,
        *,
        host: str = CLOB_HOST,
        gamma_host: str = GAMMA_HOST,
        session: aiohttp.ClientSession | None = None,
        timeout_s: float = 10.0,
    ) -> None:
        self.host = host.rstrip("/")
        self.gamma_host = gamma_host.rstrip("/")
        self._creds = credentials
        self._session = session
        self._owns_session = session is None
        self._timeout = aiohttp.ClientTimeout(total=timeout_s)
        self._client: Any | None = None  # lazily built ClobClient
        self._tick_cache: dict[str, int] = {}

    # -- plumbing -----------------------------------------------------------

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
            self._owns_session = True
        return self._session

    async def _get(self, base: str, path: str, **params: Any) -> Any:
        session = await self._get_session()
        async with session.get(f"{base}{path}", params=params or None) as resp:
            if resp.status == 429:
                raise RateLimitError(
                    "Polymarket rate limit",
                    venue=self.venue.value,
                    retry_after_s=float(resp.headers.get("Retry-After", 1)),
                )
            if resp.status >= 400:
                raise VenueError(
                    f"Polymarket GET {path} -> {resp.status}: {await resp.text()}",
                    venue=self.venue.value,
                    retryable=resp.status >= 500,
                )
            return await resp.json()

    def _clob(self) -> Any:
        """Build the official client lazily; it is only needed for writes."""
        if self._client is not None:
            return self._client
        if self._creds is None:
            raise AuthError(
                "Polymarket credentials required for trading",
                venue=self.venue.value,
            )
        try:
            from py_clob_client.client import ClobClient
            from py_clob_client.clob_types import ApiCreds
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise VenueError(
                "py-clob-client is required for Polymarket trading; "
                "install with the 'web3' extra",
                venue=self.venue.value,
            ) from exc

        creds = (
            ApiCreds(
                api_key=self._creds.api_key,
                api_secret=self._creds.api_secret,
                api_passphrase=self._creds.api_passphrase,
            )
            if self._creds.has_api_creds
            else None
        )
        client = ClobClient(
            self.host,
            chain_id=self._creds.chain_id,
            key=self._creds.private_key,
            creds=creds,
            signature_type=self._creds.signature_type,
            funder=self._creds.funder or None,
        )
        if creds is None:
            # Derive deterministic API credentials from the wallet key so a
            # fresh deployment can bootstrap itself without manual steps.
            client.set_api_creds(client.create_or_derive_api_creds())
        self._client = client
        return client

    async def _call(self, fn: str, *args: Any, **kwargs: Any) -> Any:
        """Run a synchronous ClobClient method off the event loop."""
        client = self._clob()
        method = getattr(client, fn)
        return await asyncio.to_thread(lambda: method(*args, **kwargs))

    # -- reference data -----------------------------------------------------

    async def list_markets(
        self, *, status: str | None = "active", limit: int = 200
    ) -> list[Market]:
        params: dict[str, Any] = {"limit": min(limit, 500), "order": "volume24hr"}
        if status == "active":
            params["closed"] = "false"
            params["active"] = "true"
        payload = await self._get(self.gamma_host, "/markets", **params)
        rows = payload if isinstance(payload, list) else payload.get("data") or []
        out: list[Market] = []
        for raw in rows:
            out.extend(parse_gamma_market(raw))
            if len(out) >= limit:
                break
        return out[:limit]

    async def get_market(self, venue_id: str) -> Market:
        """Look up a single market by CLOB token id."""
        payload = await self._get(self.host, f"/markets/{venue_id}")
        markets = parse_gamma_market(payload)
        for m in markets:
            if m.venue_id == venue_id:
                return m
        if markets:
            return markets[0]
        raise VenueError(f"unknown token {venue_id}", venue=self.venue.value)

    async def get_tick_pips(self, venue_id: str) -> int:
        """Tick size for a token, cached — it is fixed per market."""
        if venue_id not in self._tick_cache:
            payload = await self._get(self.host, "/tick-size", token_id=venue_id)
            raw = payload.get("minimum_tick_size", 0.01) if isinstance(payload, dict) else 0.01
            self._tick_cache[venue_id] = max(1, dollars_to_pips(float(raw)))
        return self._tick_cache[venue_id]

    async def is_neg_risk(self, venue_id: str) -> bool:
        """Whether the market uses the neg-risk adapter.

        Neg-risk markets let a complete set of mutually exclusive NO positions
        be converted efficiently, which is what makes multi-outcome dutch-book
        trades capital-efficient rather than capital-crushing.
        """
        payload = await self._get(self.host, "/neg-risk", token_id=venue_id)
        return bool(payload.get("neg_risk")) if isinstance(payload, dict) else False

    # -- market data --------------------------------------------------------

    async def get_book(self, venue_id: str, *, depth: int = 10) -> OrderBook:
        payload = await self._get(self.host, "/book", token_id=venue_id)
        book = parse_clob_book(self.market_key(venue_id), payload)
        if depth:
            book = OrderBook(
                market_key=book.market_key,
                timestamp=book.timestamp,
                bids=book.bids[:depth],
                asks=book.asks[:depth],
                sequence=book.sequence,
            )
        return book

    async def get_books(self, venue_ids: Sequence[str]) -> list[OrderBook]:
        """Batch book fetch — one request instead of N.

        The scanner polls a wide universe, so this is the difference between
        staying inside the rate limit and being throttled off the venue.
        """
        session = await self._get_session()
        body = [{"token_id": t} for t in venue_ids]
        async with session.post(f"{self.host}/books", json=body) as resp:
            if resp.status >= 400:
                raise VenueError(
                    f"Polymarket /books -> {resp.status}",
                    venue=self.venue.value,
                    retryable=resp.status >= 500,
                )
            payload = await resp.json()
        out: list[OrderBook] = []
        for raw in payload or []:
            token = str(raw.get("asset_id") or raw.get("token_id") or "")
            if token:
                out.append(parse_clob_book(self.market_key(token), raw))
        return out

    async def stream_books(
        self, venue_ids: Sequence[str]
    ) -> AsyncIterator[OrderBook]:
        """Stream book updates over the CLOB market websocket."""
        session = await self._get_session()
        ws_url = self.host.replace("https://", "wss://").replace("http://", "ws://")
        async with session.ws_connect(f"{ws_url}/ws/market") as ws:
            await ws.send_json({"assets_ids": list(venue_ids), "type": "market"})
            async for msg in ws:
                if msg.type is not aiohttp.WSMsgType.TEXT:
                    continue
                data = msg.json()
                events = data if isinstance(data, list) else [data]
                for event in events:
                    if event.get("event_type") not in ("book", "price_change"):
                        continue
                    token = str(event.get("asset_id") or "")
                    if token:
                        yield parse_clob_book(self.market_key(token), event)

    async def get_trades(self, venue_id: str, *, limit: int = 100) -> list[Trade]:
        payload = await self._get(
            self.host, "/data/trades", market=venue_id, limit=limit
        )
        rows = payload if isinstance(payload, list) else payload.get("data") or []
        out: list[Trade] = []
        for raw in rows:
            with contextlib.suppress(TypeError, ValueError):
                out.append(
                    Trade(
                        market_key=self.market_key(venue_id),
                        timestamp=datetime.fromtimestamp(
                            int(raw.get("match_time") or raw.get("timestamp") or 0),
                            tz=UTC,
                        ),
                        price_pips=dollars_to_pips(float(raw["price"])),
                        size=int(float(raw["size"])),
                        taker_side=(
                            Side.BUY if str(raw.get("side", "")).upper() == "BUY"
                            else Side.SELL
                        ),
                    )
                )
        return out

    # -- trading ------------------------------------------------------------

    async def place_order(self, request: OrderRequest) -> Order:
        from py_clob_client.clob_types import OrderArgs
        from py_clob_client.clob_types import OrderType as ClobOrderType

        order = Order(request=request)
        token_id = request.market_key.split(":", 1)[1]
        if request.price_pips is None:
            return order.with_status(
                OrderStatus.REJECTED,
                reason="Polymarket requires a limit price; market orders are "
                "expressed as marketable limits",
            )

        args = OrderArgs(
            token_id=token_id,
            price=pips_to_dollars(request.price_pips),
            size=float(request.size),
            side="BUY" if request.side is Side.BUY else "SELL",
        )
        order_type = (
            ClobOrderType.FOK
            if request.time_in_force is TimeInForce.FOK
            else ClobOrderType.GTC
        )
        post_only = request.time_in_force is TimeInForce.POST_ONLY

        try:
            signed = await self._call("create_order", args)
            resp = await self._call(
                "post_order", signed, orderType=order_type, post_only=post_only
            )
        except VenueError:
            raise
        except Exception as exc:  # SDK raises its own exception types
            return order.with_status(OrderStatus.REJECTED, reason=str(exc))

        if not isinstance(resp, dict) or not resp.get("success", True):
            return order.with_status(
                OrderStatus.REJECTED, reason=str(resp.get("errorMsg", resp))
            )
        order.venue_order_id = str(resp.get("orderID") or resp.get("orderId") or "")
        status = str(resp.get("status", "")).lower()
        order.status = {
            "matched": OrderStatus.FILLED,
            "live": OrderStatus.OPEN,
            "delayed": OrderStatus.OPEN,
        }.get(status, OrderStatus.OPEN)
        return order

    async def cancel_order(self, order: Order) -> Order:
        if not order.venue_order_id:
            return order.with_status(OrderStatus.CANCELED, reason="never acknowledged")
        with contextlib.suppress(Exception):
            await self._call("cancel", order.venue_order_id)
        return order.with_status(OrderStatus.CANCELED)

    async def cancel_all(self) -> int:
        """Cancel every resting order in one venue call. Used by the kill switch."""
        try:
            resp = await self._call("cancel_all")
        except Exception as exc:
            raise VenueError(
                f"cancel_all failed: {exc}", venue=self.venue.value, retryable=True
            ) from exc
        canceled = resp.get("canceled") if isinstance(resp, dict) else None
        return len(canceled) if isinstance(canceled, list) else 0

    async def get_open_orders(self) -> list[Order]:
        rows = await self._call("get_orders")
        out: list[Order] = []
        for raw in rows or []:
            with contextlib.suppress(KeyError, TypeError, ValueError):
                size = int(float(raw["original_size"]))
                req = OrderRequest(
                    market_key=self.market_key(str(raw["asset_id"])),
                    side=Side.BUY if str(raw["side"]).upper() == "BUY" else Side.SELL,
                    size=size,
                    price_pips=dollars_to_pips(float(raw["price"])),
                    client_order_id=str(raw.get("id") or ""),
                )
                order = Order(request=req, venue_order_id=str(raw.get("id") or ""))
                order.status = OrderStatus.OPEN
                order.filled_size = int(float(raw.get("size_matched") or 0))
                if order.filled_size:
                    order.status = OrderStatus.PARTIALLY_FILLED
                out.append(order)
        return out

    async def get_fills(self, *, since: datetime | None = None) -> list[Fill]:
        from py_clob_client.clob_types import TradeParams

        params = TradeParams(after=int(since.timestamp()) if since else None)
        rows = await self._call("get_trades", params)
        out: list[Fill] = []
        for raw in rows or []:
            with contextlib.suppress(KeyError, TypeError, ValueError):
                out.append(
                    Fill(
                        market_key=self.market_key(str(raw["asset_id"])),
                        timestamp=datetime.fromtimestamp(
                            int(raw.get("match_time") or 0), tz=UTC
                        ),
                        side=(
                            Side.BUY
                            if str(raw["side"]).upper() == "BUY"
                            else Side.SELL
                        ),
                        size=int(float(raw["size"])),
                        price_pips=dollars_to_pips(float(raw["price"])),
                        fee_pips=dollars_to_pips(float(raw.get("fee_rate_bps", 0) or 0)),
                        liquidity=str(raw.get("maker_or_taker", "taker")).lower(),
                        order_id=str(raw.get("order_id") or ""),
                        client_order_id=str(raw.get("order_id") or ""),
                        venue_fill_id=str(raw.get("id") or "") or None,
                    )
                )
        return out

    # -- account ------------------------------------------------------------

    async def get_balance(self) -> Balance:
        from py_clob_client.clob_types import AssetType, BalanceAllowanceParams

        params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
        resp = await self._call("get_balance_allowance", params)
        raw = resp.get("balance", 0) if isinstance(resp, dict) else 0
        # USDC has 6 decimals on Polygon.
        usdc = float(raw) / 1_000_000
        return Balance(venue=self.venue, cash_pips=dollars_to_pips(usdc))

    async def get_positions(self) -> list[Position]:
        """Positions are token balances; derived from the data API.

        Polymarket has no "positions" endpoint in the CLOB client — holdings
        are ERC-1155 balances of outcome tokens. The engine reconciles against
        its own fill history and treats this as the authoritative cross-check.
        """
        if self._creds is None:
            return []
        address = self._creds.funder
        if not address:
            return []
        payload = await self._get(
            "https://data-api.polymarket.com", "/positions", user=address
        )
        rows = payload if isinstance(payload, list) else payload.get("data") or []
        out: list[Position] = []
        for raw in rows:
            with contextlib.suppress(KeyError, TypeError, ValueError):
                size = int(float(raw["size"]))
                if size == 0:
                    continue
                pos = Position(market_key=self.market_key(str(raw["asset"])), size=size)
                pos.cost_basis_pips = dollars_to_pips(
                    float(raw.get("avgPrice", 0)) * size
                )
                out.append(pos)
        return out

    async def close(self) -> None:
        if self._session and self._owns_session and not self._session.closed:
            await self._session.close()
