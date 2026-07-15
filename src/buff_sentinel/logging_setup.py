"""Logging setup: JSON-lite structured records with credential redaction."""

from __future__ import annotations

import logging
import re
import sys

_SECRET_KEY_RE = re.compile(
    r"(authorization|api[_-]?key|access[_-]?token|client[_-]?secret|cookie)",
    re.IGNORECASE,
)


class RedactingFilter(logging.Filter):
    """Redacts obvious secret values in log messages."""

    _VALUE_PATTERNS = [
        (re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+", re.IGNORECASE), r"\1<redacted>"),
        (
            re.compile(
                r"((?:api[_-]?key|token|secret|cookie)\s*[:=]\s*)"
                r"['\"]?[A-Za-z0-9._\-]+['\"]?",
                re.IGNORECASE,
            ),
            r"\1<redacted>",
        ),
    ]

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        message = record.getMessage()
        for pattern, replacement in self._VALUE_PATTERNS:
            message = pattern.sub(replacement, message)
        record.msg = message
        record.args = ()
        return True


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if getattr(root, "_buff_configured", False):
        root.setLevel(level.upper())
        return

    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)s %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )
    handler.addFilter(RedactingFilter())
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    root._buff_configured = True  # type: ignore[attr-defined]


def is_secret_key(key: str) -> bool:
    return bool(_SECRET_KEY_RE.search(key))
