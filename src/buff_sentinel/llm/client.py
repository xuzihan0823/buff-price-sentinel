"""OpenAI-compatible chat client with strict JSON validation."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from buff_sentinel.config.schema import LLMConfig

LOG = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a disciplined trading analyst for CS2 skins on the BUFF marketplace. "
    "Given numeric price windows for a single goods_id, output a compact JSON with "
    "keys: verdict (buy|hold|sell|watch|skip), confidence (0..1 float), risk (low|"
    "medium|high), reasoning (<=280 chars, plain text), suggested_action (<=140 "
    "chars). Do not include prose outside the JSON."
)


class LLMError(Exception):
    """Raised when the LLM call fails and fail_open is disabled."""


class AnalysisSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    verdict: Literal["buy", "hold", "sell", "watch", "skip"]
    confidence: float = Field(ge=0.0, le=1.0)
    risk: Literal["low", "medium", "high"]
    reasoning: str
    suggested_action: str

    @field_validator("reasoning", "suggested_action")
    @classmethod
    def _cap_length(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("empty text")
        return value[:280]


@dataclass(slots=True)
class LLMAnalysisResult:
    ok: bool
    status: str  # 'ok' | 'invalid' | 'error' | 'skipped'
    model: str
    data: dict[str, Any] | None = None
    error: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class LLMClient:
    """Small wrapper around the OpenAI-compatible chat/completions endpoint."""

    def __init__(
        self,
        config: LLMConfig,
        *,
        client: httpx.AsyncClient | None = None,
        sleep: Any = None,
    ) -> None:
        self.config = config
        self._external_client = client is not None
        self._client = client or httpx.AsyncClient(
            base_url=config.base_url,
            timeout=config.timeout_seconds,
        )
        self._sleep = sleep or asyncio.sleep

    async def aclose(self) -> None:
        if not self._external_client:
            await self._client.aclose()

    async def analyze(
        self,
        summary: dict[str, Any],
        *,
        item_kind: str,
        trigger: str,
    ) -> LLMAnalysisResult:
        user_content = json.dumps(
            {"kind": item_kind, "trigger": trigger, "summary": summary},
            ensure_ascii=False,
            sort_keys=True,
        )
        base_body: dict[str, Any] = {
            "model": self.config.model_id,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

        # First attempt asks for strict JSON via response_format. If the
        # upstream rejects that feature (400/422 with a response_format hint),
        # retry once without it and rely on prompt + schema validation.
        use_response_format = True
        attempts = self.config.max_retries + 1
        last_error: str | None = None
        for attempt in range(1, attempts + 1):
            body = dict(base_body)
            if use_response_format:
                body["response_format"] = {"type": "json_object"}
            try:
                resp = await self._client.post(
                    "/chat/completions", json=body, headers=headers
                )
            except httpx.HTTPError as exc:
                last_error = f"http_error: {exc}"
                LOG.warning("llm http error attempt=%s: %s", attempt, exc)
                if attempt >= attempts:
                    break
                await self._sleep(min(2**attempt, 8))
                continue
            if resp.status_code == 200:
                try:
                    payload = resp.json()
                except ValueError as exc:
                    last_error = f"invalid_json: {exc}"
                    break
                return self._parse_choice(payload)
            if (
                resp.status_code in (400, 422)
                and use_response_format
                and _looks_like_response_format_error(resp)
            ):
                LOG.warning(
                    "llm response_format unsupported (status=%s); retrying without it",
                    resp.status_code,
                )
                use_response_format = False
                last_error = f"response_format_unsupported_{resp.status_code}"
                continue
            if resp.status_code in (408, 425, 429) or resp.status_code >= 500:
                last_error = f"status_{resp.status_code}"
                LOG.warning(
                    "llm transient status=%s attempt=%s", resp.status_code, attempt
                )
                if attempt >= attempts:
                    break
                await self._sleep(min(2**attempt, 8))
                continue
            last_error = f"status_{resp.status_code}"
            break

        return self._fail(last_error or "unknown_error")

    def _parse_choice(self, payload: dict[str, Any]) -> LLMAnalysisResult:
        choices = payload.get("choices") if isinstance(payload, dict) else None
        if not isinstance(choices, list) or not choices:
            return LLMAnalysisResult(
                ok=False,
                status="invalid",
                model=self.config.model_id,
                error="missing_choices",
                raw=payload if isinstance(payload, dict) else {},
            )
        first = choices[0]
        message = first.get("message") if isinstance(first, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            return LLMAnalysisResult(
                ok=False,
                status="invalid",
                model=self.config.model_id,
                error="empty_content",
                raw=payload,
            )
        try:
            parsed = json.loads(content)
        except ValueError as exc:
            return LLMAnalysisResult(
                ok=False,
                status="invalid",
                model=self.config.model_id,
                error=f"json_parse: {exc}",
                raw=payload,
            )
        try:
            schema = AnalysisSchema.model_validate(parsed)
        except ValidationError as exc:
            return LLMAnalysisResult(
                ok=False,
                status="invalid",
                model=self.config.model_id,
                error=f"schema: {exc.errors()}",
                raw=payload,
            )
        return LLMAnalysisResult(
            ok=True,
            status="ok",
            model=self.config.model_id,
            data=schema.model_dump(),
            raw=payload,
        )

    def _fail(self, message: str) -> LLMAnalysisResult:
        LOG.warning("llm analysis failed: %s (fail_open=%s)", message, self.config.fail_open)
        if not self.config.fail_open:
            raise LLMError(message)
        return LLMAnalysisResult(
            ok=False,
            status="error",
            model=self.config.model_id,
            error=message,
        )


def _looks_like_response_format_error(resp: httpx.Response) -> bool:
    """True only for 400/422 responses that complain about response_format.

    Authentication, quota, and other 4xx errors must NOT trigger the
    response_format fallback, because retrying without it would not help and
    would mask the real problem.
    """
    try:
        body = resp.json()
    except ValueError:
        text = resp.text or ""
        return "response_format" in text or "response format" in text.lower()
    text_blob = json.dumps(body, ensure_ascii=False).lower()
    return "response_format" in text_blob or "response format" in text_blob
