from __future__ import annotations

import random
from typing import Any

import httpx
import respx

from buff_sentinel.buff.client import BuffClient
from buff_sentinel.config.schema import BuffConfig


class _NoSleep:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def _sell_body(items: list[dict[str, Any]], total: int | None = None) -> dict[str, Any]:
    return {
        "code": "OK",
        "data": {
            "items": items,
            "total_count": total if total is not None else len(items),
            "goods_infos": {
                "1": {"steam_price_cny": "120.5"},
            },
        },
    }


def _buy_body(items: list[dict[str, Any]], total: int | None = None) -> dict[str, Any]:
    return {
        "code": 0,
        "data": {
            "items": items,
            "total_count": total if total is not None else len(items),
        },
    }


def _make_client(base_url: str = "https://buff.163.com") -> tuple[BuffClient, _NoSleep]:
    cfg = BuffConfig(
        base_url=base_url,
        request_interval_ms=0,
        jitter_ms=0,
        max_concurrency=1,
        timeout_seconds=2.0,
        max_retries=2,
    )
    sleep = _NoSleep()
    client = BuffClient(cfg, sleep=sleep, rng=random.Random(0))
    return client, sleep


@respx.mock
async def test_fetch_quote_ok() -> None:
    client, _sleep = _make_client()
    respx.get("https://buff.163.com/api/market/goods/sell_order").mock(
        return_value=httpx.Response(
            200,
            json=_sell_body(
                [{"price": "108.5"}, {"price": "115.0"}, {"price": "999.9"}],
                total=42,
            ),
        )
    )
    respx.get("https://buff.163.com/api/market/goods/buy_order").mock(
        return_value=httpx.Response(
            200,
            json=_buy_body([{"price": "100.0"}, {"price": "97.5"}], total=17),
        )
    )
    try:
        quote = await client.fetch_quote(762000)
    finally:
        await client.aclose()
    assert quote.sell_min_price == 108.5
    assert quote.sell_listing_count == 42
    assert quote.buy_max_price == 100.0
    assert quote.buy_order_count == 17
    assert quote.sell_reference_price == 120.5
    assert quote.partial is False


@respx.mock
async def test_partial_when_buy_fails() -> None:
    client, _sleep = _make_client()
    respx.get("https://buff.163.com/api/market/goods/sell_order").mock(
        return_value=httpx.Response(200, json=_sell_body([{"price": "12"}]))
    )
    respx.get("https://buff.163.com/api/market/goods/buy_order").mock(
        return_value=httpx.Response(500, json={"code": "ERR"})
    )
    try:
        quote = await client.fetch_quote(1)
    finally:
        await client.aclose()
    assert quote.partial is True
    assert quote.sell_min_price == 12.0
    assert quote.buy_max_price is None


@respx.mock
async def test_transient_then_success() -> None:
    client, sleep = _make_client()
    sell_route = respx.get("https://buff.163.com/api/market/goods/sell_order")
    sell_route.side_effect = [
        httpx.Response(429, json={"code": "RATE"}),
        httpx.Response(200, json=_sell_body([{"price": "88"}])),
    ]
    respx.get("https://buff.163.com/api/market/goods/buy_order").mock(
        return_value=httpx.Response(200, json=_buy_body([{"price": "70"}]))
    )
    try:
        quote = await client.fetch_quote(5)
    finally:
        await client.aclose()
    assert quote.sell_min_price == 88.0
    assert quote.buy_max_price == 70.0
    assert sleep.calls  # backoff was applied


@respx.mock
async def test_missing_prices_do_not_become_zero() -> None:
    client, _sleep = _make_client()
    respx.get("https://buff.163.com/api/market/goods/sell_order").mock(
        return_value=httpx.Response(200, json=_sell_body([{"price": "0"}, {"price": None}]))
    )
    respx.get("https://buff.163.com/api/market/goods/buy_order").mock(
        return_value=httpx.Response(200, json=_buy_body([{"price": "abc"}]))
    )
    try:
        quote = await client.fetch_quote(1)
    finally:
        await client.aclose()
    assert quote.sell_min_price is None
    assert quote.buy_max_price is None
    # Non-price fields still convey totals.
    assert quote.sell_listing_count is not None
    assert quote.buy_order_count is not None
