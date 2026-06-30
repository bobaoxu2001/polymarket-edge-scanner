"""Thin, defensive client for Polymarket's public read APIs.

Only *public, documented, read-only* endpoints are used:

* Gamma API  (``/markets``)            — market metadata, prices, liquidity.
* CLOB  API  (``/book``, ``/price``)   — order book depth & quotes.

The client adds: a polite rate limiter, an in-memory TTL response cache,
on-disk caching of raw market pulls (for auditing), bounded retries, and
graceful error handling. It performs **no** authenticated or trading calls.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import httpx

from backend.config import settings

_RAW_DIR = Path(settings.external_signals_path).parent.parent / "data" / "raw"


class PolymarketAPIError(RuntimeError):
    """Raised when the Polymarket API cannot satisfy a request."""


class _RateLimiter:
    """Enforces a minimum wall-clock interval between outbound requests."""

    def __init__(self, min_interval: float) -> None:
        self._min_interval = min_interval
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self) -> None:
        with self._lock:
            delta = time.monotonic() - self._last
            if delta < self._min_interval:
                time.sleep(self._min_interval - delta)
            self._last = time.monotonic()


class _TTLCache:
    """Tiny thread-safe TTL cache for idempotent GETs."""

    def __init__(self, ttl: float) -> None:
        self._ttl = ttl
        self._lock = threading.Lock()
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        with self._lock:
            hit = self._store.get(key)
            if hit and (time.monotonic() - hit[0]) < self._ttl:
                return hit[1]
            return None

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._store[key] = (time.monotonic(), value)


class PolymarketClient:
    """Read-only Polymarket data client (Gamma + CLOB)."""

    def __init__(
        self,
        gamma_base: str | None = None,
        clob_base: str | None = None,
        *,
        timeout: float | None = None,
        min_interval: float | None = None,
        cache_ttl: float | None = None,
    ) -> None:
        self.gamma_base = (gamma_base or settings.polymarket_gamma_base).rstrip("/")
        self.clob_base = (clob_base or settings.polymarket_clob_base).rstrip("/")
        self._limiter = _RateLimiter(
            min_interval if min_interval is not None else settings.http_min_interval_seconds
        )
        self._cache = _TTLCache(
            cache_ttl if cache_ttl is not None else settings.http_cache_ttl_seconds
        )
        self._client = httpx.Client(
            timeout=timeout or settings.http_timeout_seconds,
            headers={
                "User-Agent": "polymarket-edge-scanner/0.1 (research; read-only)",
                "Accept": "application/json",
            },
            follow_redirects=True,
        )

    # ---- low-level ---------------------------------------------------------
    def _get(self, url: str, params: dict | None = None, *, retries: int = 3) -> Any:
        cache_key = url + "?" + json.dumps(params or {}, sort_keys=True)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        last_err: Exception | None = None
        for attempt in range(retries):
            self._limiter.wait()
            try:
                resp = self._client.get(url, params=params)
                if resp.status_code == 429:  # rate limited — back off
                    time.sleep(1.5 * (attempt + 1))
                    last_err = PolymarketAPIError("429 rate limited")
                    continue
                resp.raise_for_status()
                data = resp.json()
                self._cache.set(cache_key, data)
                return data
            except (httpx.HTTPError, json.JSONDecodeError) as exc:
                last_err = exc
                time.sleep(0.4 * (attempt + 1))
        raise PolymarketAPIError(f"GET {url} failed after {retries} tries: {last_err}")

    # ---- Gamma (markets) ---------------------------------------------------
    def fetch_active_markets(
        self, *, limit: int | None = None, min_liquidity: float = 0.0
    ) -> list[dict]:
        """Fetch active, open, order-book-enabled markets.

        Pages through ``/markets`` (Gamma) and writes the raw pull to
        ``data/raw/`` for auditing. Errors are surfaced as
        :class:`PolymarketAPIError`.
        """
        target = limit or settings.market_fetch_limit
        page_size = 100
        offset = 0
        out: list[dict] = []
        while len(out) < target:
            params = {
                "active": "true",
                "closed": "false",
                "limit": page_size,
                "offset": offset,
                "order": "liquidity",
                "ascending": "false",
            }
            if min_liquidity > 0:
                params["liquidity_num_min"] = min_liquidity
            batch = self._get(f"{self.gamma_base}/markets", params)
            if not isinstance(batch, list) or not batch:
                break
            out.extend(batch)
            offset += page_size
            if len(batch) < page_size:
                break
        out = out[:target]
        self._dump_raw("markets_latest.json", out)
        return out

    def fetch_market(self, market_id: str) -> dict | None:
        """Fetch a single market by its Gamma id."""
        try:
            data = self._get(f"{self.gamma_base}/markets/{market_id}")
        except PolymarketAPIError:
            return None
        if isinstance(data, list):
            return data[0] if data else None
        return data if isinstance(data, dict) else None

    # ---- CLOB (order book / quotes) ---------------------------------------
    def fetch_orderbook(self, token_id: str) -> dict | None:
        """Fetch the order book for a CLOB outcome token, or ``None`` on failure."""
        if not token_id:
            return None
        try:
            return self._get(f"{self.clob_base}/book", {"token_id": token_id})
        except PolymarketAPIError:
            return None

    def fetch_price(self, token_id: str, side: str = "buy") -> float | None:
        """Fetch the best quote for a token on a given side (``buy``/``sell``)."""
        if not token_id:
            return None
        try:
            data = self._get(
                f"{self.clob_base}/price", {"token_id": token_id, "side": side}
            )
            return float(data["price"]) if data and "price" in data else None
        except (PolymarketAPIError, KeyError, ValueError, TypeError):
            return None

    # ---- helpers -----------------------------------------------------------
    def _dump_raw(self, name: str, data: Any) -> None:
        try:
            _RAW_DIR.mkdir(parents=True, exist_ok=True)
            (_RAW_DIR / name).write_text(json.dumps(data)[:5_000_000])
        except OSError:
            pass  # caching is best-effort; never block a scan on disk issues

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "PolymarketClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
