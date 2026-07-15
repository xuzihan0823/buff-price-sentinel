"""Compute rolling trend windows from price snapshots."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median

from buff_sentinel.storage.models import PriceSnapshot


@dataclass(slots=True)
class Window:
    label: str
    samples: int
    first: float | None
    last: float | None
    minimum: float | None
    maximum: float | None
    median: float | None
    change_pct: float | None


@dataclass(slots=True)
class TrendSummary:
    goods_id: int
    now: datetime
    latest_sell: float | None
    latest_buy: float | None
    coverage_ratio: float
    windows: dict[str, Window]

    def as_prompt_dict(self) -> dict[str, object]:
        return {
            "goods_id": self.goods_id,
            "as_of": self.now.isoformat(),
            "latest_sell_min": self.latest_sell,
            "latest_buy_max": self.latest_buy,
            "coverage_ratio": round(self.coverage_ratio, 3),
            "windows": {
                label: {
                    "samples": win.samples,
                    "first": win.first,
                    "last": win.last,
                    "min": win.minimum,
                    "max": win.maximum,
                    "median": win.median,
                    "change_pct": win.change_pct,
                }
                for label, win in self.windows.items()
            },
        }


WINDOW_DEFINITIONS: list[tuple[str, timedelta]] = [
    ("1h", timedelta(hours=1)),
    ("6h", timedelta(hours=6)),
    ("24h", timedelta(hours=24)),
    ("3d", timedelta(days=3)),
    ("7d", timedelta(days=7)),
]


def compute_trends(
    goods_id: int,
    snapshots: Sequence[PriceSnapshot],
    now: datetime,
) -> TrendSummary:
    ordered = sorted(snapshots, key=lambda s: s.captured_at)
    latest_sell = None
    latest_buy = None
    for snap in reversed(ordered):
        if latest_sell is None and snap.sell_min_price is not None:
            latest_sell = snap.sell_min_price
        if latest_buy is None and snap.buy_max_price is not None:
            latest_buy = snap.buy_max_price
        if latest_sell is not None and latest_buy is not None:
            break

    windows: dict[str, Window] = {}
    for label, delta in WINDOW_DEFINITIONS:
        cutoff = now - delta
        subset = [s for s in ordered if s.captured_at >= cutoff]
        windows[label] = _summarize(label, subset)

    # Seven-day coverage: samples / expected 10-minute buckets, capped at 1.0.
    seven_day_samples = windows["7d"].samples
    expected_buckets = int(timedelta(days=7) / timedelta(minutes=10))
    coverage = min(1.0, seven_day_samples / expected_buckets) if expected_buckets else 0.0

    return TrendSummary(
        goods_id=goods_id,
        now=now,
        latest_sell=latest_sell,
        latest_buy=latest_buy,
        coverage_ratio=coverage,
        windows=windows,
    )


def _summarize(label: str, subset: Sequence[PriceSnapshot]) -> Window:
    sells = [s.sell_min_price for s in subset if s.sell_min_price is not None]
    if not sells:
        return Window(
            label=label,
            samples=len(subset),
            first=None,
            last=None,
            minimum=None,
            maximum=None,
            median=None,
            change_pct=None,
        )
    first = sells[0]
    last = sells[-1]
    change_pct = None
    if first > 0:
        change_pct = round((last - first) / first * 100.0, 4)
    return Window(
        label=label,
        samples=len(sells),
        first=round(first, 4),
        last=round(last, 4),
        minimum=round(min(sells), 4),
        maximum=round(max(sells), 4),
        median=round(median(sells), 4),
        change_pct=change_pct,
    )
