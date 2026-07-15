from __future__ import annotations

import datetime as _dt

import httpx
import respx

from buff_sentinel.config.schema import QQBotConfig
from buff_sentinel.notifier.formatter import (
    format_alert_text,
    format_recovery_summary,
)
from buff_sentinel.notifier.qq import QQBotClient


def _config() -> QQBotConfig:
    return QQBotConfig(
        token_url="https://bots.qq.com/app/getAppAccessToken",
        message_base_url="https://api.sgroup.qq.com",
        app_id="app",
        client_secret="secret",
        recipients=["openid-1"],
        timeout_seconds=2.0,
        max_retries=1,
    )


class _Clock:
    def __init__(self) -> None:
        self.t = 1_000_000.0

    def __call__(self) -> float:
        return self.t


@respx.mock
async def test_token_fetch_and_reuse() -> None:
    clock = _Clock()
    respx.post("https://bots.qq.com/app/getAppAccessToken").mock(
        return_value=httpx.Response(
            200, json={"access_token": "abc", "expires_in": 7200}
        )
    )
    client = QQBotClient(_config(), clock=clock)
    try:
        token = await client.get_access_token()
        assert token == "abc"
        # Second call within TTL uses the cache.
        token_again = await client.get_access_token()
        assert token_again == "abc"
        assert respx.calls.call_count == 1
    finally:
        await client.aclose()


@respx.mock
async def test_send_success() -> None:
    respx.post("https://bots.qq.com/app/getAppAccessToken").mock(
        return_value=httpx.Response(
            200, json={"access_token": "abc", "expires_in": 7200}
        )
    )
    respx.post("https://api.sgroup.qq.com/v2/users/openid-1/messages").mock(
        return_value=httpx.Response(200, json={"id": "m1"})
    )
    client = QQBotClient(_config())
    try:
        result = await client.send_c2c_text("openid-1", "hi")
    finally:
        await client.aclose()
    assert result.ok
    assert result.status == "sent"


@respx.mock
async def test_send_failure_records_error() -> None:
    respx.post("https://bots.qq.com/app/getAppAccessToken").mock(
        return_value=httpx.Response(
            200, json={"access_token": "abc", "expires_in": 7200}
        )
    )
    respx.post("https://api.sgroup.qq.com/v2/users/openid-1/messages").mock(
        return_value=httpx.Response(400, json={"code": "bad"})
    )
    client = QQBotClient(_config())
    try:
        result = await client.send_c2c_text("openid-1", "hi")
    finally:
        await client.aclose()
    assert not result.ok
    assert "status_400" in result.detail


def test_format_alert_includes_analysis() -> None:
    text = format_alert_text(
        name="Sample",
        goods_id=1,
        trigger="owned_profit",
        reason="P/L 12% >= 10%",
        metrics={"sell_min_price": 112, "purchase_price": 100, "pnl_pct": 12.0},
        analysis={
            "verdict": "sell",
            "confidence": 0.7,
            "risk": "medium",
            "reasoning": "trend flat",
            "suggested_action": "close half",
        },
        generated_at=_dt.datetime(2026, 7, 14, 12, 0, 0),
    )
    assert "Sample" in text
    assert "owned_profit" in text
    assert "verdict" not in text  # human-friendly line
    assert "sell" in text
    assert "close half" in text


def test_format_recovery_summary_includes_missed_preview() -> None:
    text = format_recovery_summary(
        started_at=_dt.datetime(2026, 7, 14, 12, 0, 0),
        resolved_at=_dt.datetime(2026, 7, 14, 12, 30, 0),
        failure_count=5,
        missed_alerts=[
            {
                "goods_id": 1,
                "name": "A",
                "trigger": "owned_profit",
                "fired_at": "2026-07-14T12:05",
            },
            {
                "goods_id": 2,
                "name": "B",
                "trigger": "wishlist_floor",
                "fired_at": "2026-07-14T12:10",
            },
        ],
    )
    assert "recovered" in text
    assert "duration:" in text
    assert "A" in text and "B" in text
