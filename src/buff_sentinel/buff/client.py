"""Async BUFF first-page order client with pacing and retries."""

from __future__ import annotations

import asyncio
import logging
import math
import random
from dataclasses import dataclass
from typing import Any

import httpx

from buff_sentinel.config.schema import BuffConfig

LOG = logging.getLogger(__name__)


class BuffError(Exception):
    """Any recoverable or terminal BUFF error."""


@dataclass(slots=True)
class GoodsQuote:
    goods_id: int
    sell_min_price: float | None
    sell_reference_price: float | None
    sell_listing_count: int | None
    buy_max_price: float | None
    buy_order_count: int | None
    partial: bool

    @property
    def usable(self) -> bool:
        return (
            self.sell_min_price is not None
            or self.buy_max_price is not None
            or self.sell_listing_count is not None
            or self.buy_order_count is not None
        )


class BuffClient:
    """Fetches sell/buy first-page snapshots for configured goods."""

    def __init__(
        self,
        config: BuffConfig,
        *,
        client: httpx.AsyncClient | None = None,
        sleep: Any = None,
        rng: random.Random | None = None,
    ) -> None:
        self.config = config
        self._external_client = client is not None
        self._client = client or httpx.AsyncClient(
            base_url=config.base_url,
            timeout=config.timeout_seconds,
            headers=self._default_headers(),
        )
        self._sem = asyncio.Semaphore(config.max_concurrency)
        self._sleep = sleep or asyncio.sleep
        self._rng = rng or random.Random()

    def _default_headers(self) -> dict[str, str]:
        headers = {
            "User-Agent": self.config.user_agent,
            "Accept": "application/json,text/plain,*/*",
            "Referer": self.config.base_url + "/",
        }
        if self.config.session_cookie:
            headers["Cookie"] = self.config.session_cookie
        return headers

    async def aclose(self) -> None:
        if not self._external_client:
            await self._client.aclose()

    async def fetch_quote(self, goods_id: int) -> GoodsQuote:
        async with self._sem:
            sell = await self._get_first_page(
                self.config.sell_order_path, goods_id, "sell"
            )
            await self._pace()
            buy = await self._get_first_page(
                self.config.buy_order_path, goods_id, "buy"
            )
            partial = sell is None or buy is None
            sell_min, sell_ref, sell_count = _parse_sell(sell)
            buy_max, buy_count = _parse_buy(buy)
            return GoodsQuote(
                goods_id=goods_id,
                sell_min_price=sell_min,
                sell_reference_price=sell_ref,
                sell_listing_count=sell_count,
                buy_max_price=buy_max,
                buy_order_count=buy_count,
                partial=partial,
            )

    async def _get_first_page(
        self, path: str, goods_id: int, kind: str
    ) -> dict[str, Any] | None:
        params: dict[str, str | int] = {
            "game": "csgo",
            "goods_id": goods_id,
            "page_num": 1,
            "page_size": 20,
        }
        attempts = self.config.max_retries + 1
        for attempt in range(1, attempts + 1):
            try:
                resp = await self._client.get(path, params=params)
            except httpx.HTTPError as exc:
                LOG.warning(
                    "buff %s http error goods=%s attempt=%s: %s",
                    kind, goods_id, attempt, exc,
                )
                if attempt >= attempts:
                    return None
                await self._pace(backoff=attempt)
                continue
            if resp.status_code == 200:
                try:
                    return _extract_payload(resp.json())
                except ValueError as exc:
                    LOG.warning(
                        "buff %s payload rejected goods=%s: %s", kind, goods_id, exc
                    )
                    return None
            if resp.status_code in (429,) or resp.status_code >= 500:
                LOG.warning(
                    "buff %s transient status=%s goods=%s attempt=%s",
                    kind, resp.status_code, goods_id, attempt,
                )
                if attempt >= attempts:
                    return None
                await self._pace(backoff=attempt)
                continue
            # 4xx (other than 429): permanent for this request.
            LOG.warning(
                "buff %s permanent status=%s goods=%s", kind, resp.status_code, goods_id
            )
            return None
        return None

    async def _pace(self, *, backoff: int = 0) -> None:
        base_ms = self.config.request_interval_ms * (2**backoff if backoff else 1)
        jitter = (
            self._rng.uniform(0, self.config.jitter_ms) if self.config.jitter_ms else 0.0
        )
        await self._sleep((base_ms + jitter) / 1000.0)


def _extract_payload(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ValueError("response body is not an object")
    code = body.get("code")
    if code not in (None, "OK", "ok", 0):
        raise ValueError(f"buff code={code!r}")
    data = body.get("data")
    if not isinstance(data, dict):
        raise ValueError("data field is missing")
    return data


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result) or result <= 0:  # NaN or non-positive
        return None
    return result


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        try:
            result = int(float(value))
        except (TypeError, ValueError):
            return None
    if result < 0:
        return None
    return result


def _parse_sell(
    payload: dict[str, Any] | None,
) -> tuple[float | None, float | None, int | None]:
    if not payload:
        return None, None, None
    items = payload.get("items")
    goods_infos = payload.get("goods_infos") or {}
    if isinstance(goods_infos, dict) and goods_infos:
        first_info = next(iter(goods_infos.values()))
        ref_value = first_info.get("steam_price_cny") if isinstance(first_info, dict) else None
        reference = _to_float(ref_value)
    else:
        reference = None
    sell_min: float | None = None
    listing_count: int | None = None
    if isinstance(items, list):
        listing_count = len(items)
        raw_prices = [_to_float(item.get("price")) for item in items if isinstance(item, dict)]
        prices: list[float] = [p for p in raw_prices if p is not None]
        if prices:
            sell_min = min(prices)
    total = _to_int(payload.get("total_count"))
    if total is not None:
        listing_count = total
    return sell_min, reference, listing_count


def _parse_buy(payload: dict[str, Any] | None) -> tuple[float | None, int | None]:
    if not payload:
        return None, None
    items = payload.get("items")
    buy_max: float | None = None
    order_count: int | None = None
    if isinstance(items, list):
        order_count = len(items)
        raw_prices = [_to_float(item.get("price")) for item in items if isinstance(item, dict)]
        prices: list[float] = [p for p in raw_prices if p is not None]
        if prices:
            buy_max = max(prices)
    total = _to_int(payload.get("total_count"))
    if total is not None:
        order_count = total
    return buy_max, order_count
