"""Analytics: trend windows + rule evaluation."""

from __future__ import annotations

from buff_sentinel.analytics.rules import (
    Candidate,
    RuleEngine,
    build_signal_snapshot,
)
from buff_sentinel.analytics.trends import TrendSummary, compute_trends

__all__ = [
    "Candidate",
    "RuleEngine",
    "TrendSummary",
    "build_signal_snapshot",
    "compute_trends",
]
