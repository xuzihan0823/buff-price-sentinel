"""Official QQ Bot C2C client: token cache + user private message."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from buff_sentinel.config.schema import QQBotConfig

LOG = logging.getLogger(__name__)


class QQBotError(Exception):
    """Raised when the QQ Bot API rejects the call."""


@dataclass(slots=True)
class QQSendResult:
    ok: bool
    openid: str
    status: str  # 'sent' | 'skipped' | 'error'
    detail: str = ""


class QQBotClient:
    """Manages access-token refresh and delivers C2C text messages."""

    def __init__(
        self,
        config: QQBotConfig,
        *,
        client: httpx.AsyncClient | None = None,
        clock: Any = None,
        sleep: Any = None,
    ) -> None:
        self.config = config
        self._external_client = client is not None
        self._token_client = client or httpx.AsyncClient(timeout=config.timeout_seconds)
        self._msg_client = client or httpx.AsyncClient(
            base_url=config.message_base_url, timeout=config.timeout_seconds
        )
        self._external_msg_client = client is not None
        self._clock = clock or time.time
        self._sleep = sleep or asyncio.sleep

        self._token: str | None = None
        self._token_expiry: float = 0.0

    async def aclose(self) -> None:
        if not self._external_client:
            await self._token_client.aclose()
        if not self._external_msg_client and self._msg_client is not self._token_client:
            await self._msg_client.aclose()

    # ---------------------------------------------------------------- token
    async def get_access_token(self, *, force: bool = False) -> str:
        now = self._clock()
        if not force and self._token and now < self._token_expiry - 30:
            return self._token
        payload = {
            "appId": self.config.app_id,
            "clientSecret": self.config.client_secret,
        }
        attempts = self.config.max_retries + 1
        last_error: str | None = None
        for attempt in range(1, attempts + 1):
            try:
                resp = await self._token_client.post(
                    self.config.token_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
            except httpx.HTTPError as exc:
                last_error = f"http_error: {exc}"
                if attempt >= attempts:
                    break
                await self._sleep(min(2**attempt, 8))
                continue
            if resp.status_code == 200:
                try:
                    body = resp.json()
                except ValueError as exc:
                    raise QQBotError(f"token response not JSON: {exc}") from exc
                token = body.get("access_token")
                expires_in = body.get("expires_in")
                if not token:
                    raise QQBotError(f"token response missing access_token: {body}")
                try:
                    seconds = int(expires_in)
                except (TypeError, ValueError):
                    seconds = 7000
                self._token = str(token)
                self._token_expiry = now + max(seconds, 60)
                return self._token
            last_error = f"status_{resp.status_code}"
            if resp.status_code in (429,) or resp.status_code >= 500:
                if attempt >= attempts:
                    break
                await self._sleep(min(2**attempt, 8))
                continue
            break
        raise QQBotError(last_error or "unknown token error")

    # ---------------------------------------------------------------- probe
    async def probe(self) -> bool:
        """Lightweight recovery probe.

        Always fetches an access token. If `probe_message` is configured, also
        sends it to every recipient and requires all deliveries to succeed.
        Returns True only when the probe is healthy.
        """
        try:
            await self.get_access_token(force=True)
        except QQBotError as exc:
            LOG.warning("qq probe token failed: %s", exc)
            return False
        probe_text = self.config.probe_message
        if not probe_text.strip():
            return True
        for openid in self.config.recipients:
            result = await self.send_c2c_text(openid, probe_text)
            if not result.ok:
                LOG.warning("qq probe message failed: %s", result.detail)
                return False
        return True

    # ---------------------------------------------------------------- send
    async def send_c2c_text(self, openid: str, text: str) -> QQSendResult:
        if not text.strip():
            return QQSendResult(ok=False, openid=openid, status="skipped", detail="empty text")
        body = {
            "msg_type": 0,
            "content": text,
        }

        attempts = self.config.max_retries + 1
        last_error = "unknown"
        for attempt in range(1, attempts + 1):
            try:
                token = await self.get_access_token(force=attempt > 1)
            except QQBotError as exc:
                last_error = f"token: {exc}"
                if attempt >= attempts:
                    break
                await self._sleep(min(2**attempt, 8))
                continue
            try:
                resp = await self._msg_client.post(
                    f"/v2/users/{openid}/messages",
                    json=body,
                    headers={
                        "Authorization": f"QQBot {token}",
                        "Content-Type": "application/json",
                    },
                )
            except httpx.HTTPError as exc:
                last_error = f"http_error: {exc}"
                if attempt >= attempts:
                    break
                await self._sleep(min(2**attempt, 8))
                continue
            if resp.status_code in (200, 201, 202):
                return QQSendResult(ok=True, openid=openid, status="sent")
            if resp.status_code == 401:
                # Force refresh once and retry.
                self._token = None
                last_error = "unauthorized"
                if attempt >= attempts:
                    break
                await self._sleep(1)
                continue
            if resp.status_code in (429,) or resp.status_code >= 500:
                last_error = f"status_{resp.status_code}"
                if attempt >= attempts:
                    break
                await self._sleep(min(2**attempt, 8))
                continue
            last_error = f"status_{resp.status_code}: {_safe_body(resp)}"
            break
        LOG.warning("qq send failed openid=%s: %s", openid, last_error)
        return QQSendResult(ok=False, openid=openid, status="error", detail=last_error)


def _safe_body(resp: httpx.Response) -> str:
    try:
        text = resp.text
    except (ValueError, RuntimeError):
        return "<no body>"
    return text[:200]
