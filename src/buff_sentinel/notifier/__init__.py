"""Notifier package (QQ Bot official C2C API)."""

from __future__ import annotations

from buff_sentinel.notifier.formatter import format_alert_text, format_recovery_summary
from buff_sentinel.notifier.qq import (
    QQBotClient,
    QQBotError,
    QQSendResult,
)

__all__ = [
    "QQBotClient",
    "QQBotError",
    "QQSendResult",
    "format_alert_text",
    "format_recovery_summary",
]
