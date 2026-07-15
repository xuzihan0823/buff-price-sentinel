from __future__ import annotations

import httpx
import pytest
import respx

from buff_sentinel.config.schema import LLMConfig
from buff_sentinel.llm.client import LLMClient, LLMError


def _config(fail_open: bool = True) -> LLMConfig:
    return LLMConfig(
        base_url="https://llm.example.com/v1",
        api_key="k",
        model="test",
        timeout_seconds=2.0,
        max_retries=1,
        fail_open=fail_open,
    )


def _valid_content() -> str:
    return (
        '{"verdict": "hold", "confidence": 0.65, "risk": "medium", '
        '"reasoning": "flat trend", "suggested_action": "wait 24h"}'
    )


@respx.mock
async def test_analyze_ok() -> None:
    respx.post("https://llm.example.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": _valid_content()}}],
            },
        )
    )
    client = LLMClient(_config())
    try:
        result = await client.analyze(
            {"latest_sell_min": 100},
            item_kind="owned",
            trigger="owned_profit",
        )
    finally:
        await client.aclose()
    assert result.ok
    assert result.data is not None
    assert result.data["verdict"] == "hold"


@respx.mock
async def test_invalid_json_fails_open() -> None:
    respx.post("https://llm.example.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={"choices": [{"message": {"content": "not-json"}}]},
        )
    )
    client = LLMClient(_config(fail_open=True))
    try:
        result = await client.analyze({}, item_kind="owned", trigger="owned_profit")
    finally:
        await client.aclose()
    assert not result.ok
    assert result.status == "invalid"


@respx.mock
async def test_transport_error_raises_when_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    respx.post("https://llm.example.com/v1/chat/completions").mock(
        side_effect=httpx.ConnectError("boom")
    )
    client = LLMClient(_config(fail_open=False), sleep=lambda _s: _immediate())
    try:
        with pytest.raises(LLMError):
            await client.analyze({}, item_kind="owned", trigger="owned_profit")
    finally:
        await client.aclose()


async def _immediate() -> None:
    return None


@respx.mock
async def test_schema_rejects_bad_verdict() -> None:
    respx.post("https://llm.example.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"verdict": "moon", "confidence": 0.9, "risk": "low", '
                                '"reasoning": "r", "suggested_action": "a"}'
                            )
                        }
                    }
                ]
            },
        )
    )
    client = LLMClient(_config())
    try:
        result = await client.analyze({}, item_kind="owned", trigger="owned_profit")
    finally:
        await client.aclose()
    assert not result.ok
    assert result.status == "invalid"
