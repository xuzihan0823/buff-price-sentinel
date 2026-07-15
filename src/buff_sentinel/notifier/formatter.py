"""Text formatters for alerts and recovery summaries."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any


def format_alert_text(
    *,
    name: str,
    goods_id: int,
    trigger: str,
    reason: str,
    metrics: dict[str, Any],
    analysis: dict[str, Any] | None,
    generated_at: datetime,
) -> str:
    lines = [
        f"[BUFF Sentinel] {name} ({goods_id})",
        f"trigger: {trigger}",
        f"reason: {reason}",
    ]
    price_lines = []
    for key in (
        "sell_min_price",
        "previous_sell_price",
        "buy_max_price",
        "purchase_price",
        "target_price",
        "alert_above_price",
        "pnl_pct",
        "change_pct_24h",
        "threshold_pct",
    ):
        if key in metrics and metrics[key] is not None:
            price_lines.append(f"  {key}: {metrics[key]}")
    if price_lines:
        lines.append("metrics:")
        lines.extend(price_lines)

    if analysis and analysis.get("verdict"):
        lines.append(
            "analysis: "
            f"{analysis.get('verdict')} "
            f"(conf {analysis.get('confidence')}, risk {analysis.get('risk')})"
        )
        if analysis.get("suggested_action"):
            lines.append(f"action: {analysis['suggested_action']}")
        if analysis.get("reasoning"):
            lines.append(f"note: {analysis['reasoning']}")
    else:
        lines.append("analysis: rule-only (LLM unavailable or invalid)")

    lines.append(f"at: {generated_at.isoformat(timespec='minutes')}")
    return "\n".join(lines)


def format_recovery_summary(
    *,
    started_at: datetime,
    resolved_at: datetime,
    failure_count: int,
    missed_alerts: list[dict[str, Any]],
) -> str:
    duration = resolved_at - started_at
    lines = [
        "[BUFF Sentinel] QQ delivery recovered",
        f"outage_start: {started_at.isoformat(timespec='minutes')}",
        f"outage_end:   {resolved_at.isoformat(timespec='minutes')}",
        f"duration:     {_fmt_duration(duration)}",
        f"failures:     {failure_count}",
        f"missed:       {len(missed_alerts)} alerts",
    ]
    if missed_alerts:
        preview = missed_alerts[-5:]
        lines.append("recent_missed:")
        for entry in preview:
            preview_line = _summarize_entry(entry)
            lines.append(f"  - {preview_line}")
        if len(missed_alerts) > 5:
            lines.append(f"  ... and {len(missed_alerts) - 5} more")
    return "\n".join(lines)


def _summarize_entry(entry: dict[str, Any]) -> str:
    trigger = entry.get("trigger", "?")
    name = entry.get("name", entry.get("goods_id", "?"))
    fired = entry.get("fired_at", "?")
    return f"{name} [{trigger}] at {fired}"


def _fmt_duration(delta: timedelta) -> str:
    total_seconds = int(delta.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    if minutes:
        return f"{minutes}m{seconds:02d}s"
    return f"{seconds}s"


def truncate_json(obj: dict[str, Any], limit: int = 400) -> str:
    text = json.dumps(obj, ensure_ascii=False, sort_keys=True)
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"
