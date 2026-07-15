"""Rule engine: owned P/L, wishlist floor + 24h drop, periodic review."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from buff_sentinel.analytics.trends import TrendSummary
from buff_sentinel.config.schema import OwnedItem, WishlistItem

TriggerKind = Literal[
    "owned_profit",
    "owned_loss",
    "owned_above",
    "wishlist_floor",
    "wishlist_drop",
    "wishlist_rise",
    "wishlist_review",
]


@dataclass(slots=True)
class Candidate:
    goods_id: int
    name: str
    kind: str  # 'owned' | 'wishlist'
    trigger: TriggerKind
    reason: str
    metrics: dict[str, float | int | str | None]
    dedup_bucket: str  # coarse time bucket for dedup key
    generated_at: datetime


def _bucket_hour(now: datetime, hours: int) -> str:
    epoch = int(now.timestamp())
    bucket = epoch // (hours * 3600)
    return f"h{hours}:{bucket}"


class RuleEngine:
    """Evaluates owned/wishlist rules against latest snapshot + trend windows."""

    def __init__(self, *, wishlist_review_days: int = 3) -> None:
        self.wishlist_review_days = wishlist_review_days

    # ---------------------------------------------------------------- owned
    def evaluate_owned(
        self,
        item: OwnedItem,
        trend: TrendSummary,
        now: datetime,
        *,
        previous_sell: float | None = None,
    ) -> list[Candidate]:
        if trend.latest_sell is None:
            return []
        purchase = item.purchase_price
        if purchase <= 0:
            return []
        pnl_pct = (trend.latest_sell - purchase) / purchase * 100.0

        candidates: list[Candidate] = []
        if item.profit_pct is not None and pnl_pct >= item.profit_pct:
            candidates.append(
                Candidate(
                    goods_id=item.goods_id,
                    name=item.name,
                    kind="owned",
                    trigger="owned_profit",
                    reason=(
                        f"P/L {pnl_pct:.2f}% >= profit threshold {item.profit_pct:.2f}%"
                    ),
                    metrics={
                        "sell_min_price": trend.latest_sell,
                        "purchase_price": purchase,
                        "pnl_pct": round(pnl_pct, 4),
                        "threshold_pct": item.profit_pct,
                    },
                    dedup_bucket=_bucket_hour(now, 1),
                    generated_at=now,
                )
            )
        elif item.loss_pct is not None and pnl_pct <= -item.loss_pct:
            candidates.append(
                Candidate(
                    goods_id=item.goods_id,
                    name=item.name,
                    kind="owned",
                    trigger="owned_loss",
                    reason=(
                        f"P/L {pnl_pct:.2f}% <= -loss threshold -{item.loss_pct:.2f}%"
                    ),
                    metrics={
                        "sell_min_price": trend.latest_sell,
                        "purchase_price": purchase,
                        "pnl_pct": round(pnl_pct, 4),
                        "threshold_pct": -item.loss_pct,
                    },
                    dedup_bucket=_bucket_hour(now, 1),
                    generated_at=now,
                )
            )

        threshold = item.alert_above_price
        if (
            threshold is not None
            and previous_sell is not None
            and previous_sell < threshold <= trend.latest_sell
        ):
            candidates.append(
                Candidate(
                    goods_id=item.goods_id,
                    name=item.name,
                    kind="owned",
                    trigger="owned_above",
                    reason=(
                        f"sell_min crossed above {threshold:.2f}: "
                        f"{previous_sell:.2f} -> {trend.latest_sell:.2f}"
                    ),
                    metrics={
                        "sell_min_price": trend.latest_sell,
                        "previous_sell_price": previous_sell,
                        "purchase_price": purchase,
                        "pnl_pct": round(pnl_pct, 4),
                        "alert_above_price": threshold,
                    },
                    dedup_bucket=_bucket_hour(now, 1),
                    generated_at=now,
                )
            )
        return candidates

    # ---------------------------------------------------------------- wishlist
    def evaluate_wishlist(
        self,
        item: WishlistItem,
        trend: TrendSummary,
        now: datetime,
        last_analysis: datetime | None,
    ) -> list[Candidate]:
        candidates: list[Candidate] = []
        if trend.latest_sell is None:
            # No usable price: still allow periodic review to run.
            if self._needs_review(last_analysis, now):
                candidates.append(self._review_candidate(item, trend, now))
            return candidates

        if item.target_price is not None and trend.latest_sell <= item.target_price:
            candidates.append(
                Candidate(
                    goods_id=item.goods_id,
                    name=item.name,
                    kind="wishlist",
                    trigger="wishlist_floor",
                    reason=(
                        f"sell_min {trend.latest_sell:.2f} <= target {item.target_price:.2f}"
                    ),
                    metrics={
                        "sell_min_price": trend.latest_sell,
                        "target_price": item.target_price,
                    },
                    dedup_bucket=_bucket_hour(now, 1),
                    generated_at=now,
                )
            )

        if item.drop_pct_24h is not None:
            window = trend.windows.get("24h")
            if window and window.change_pct is not None and window.change_pct <= -item.drop_pct_24h:
                candidates.append(
                    Candidate(
                        goods_id=item.goods_id,
                        name=item.name,
                        kind="wishlist",
                        trigger="wishlist_drop",
                        reason=(
                            f"24h change {window.change_pct:.2f}% <= -{item.drop_pct_24h:.2f}%"
                        ),
                        metrics={
                            "sell_min_price": trend.latest_sell,
                            "change_pct_24h": window.change_pct,
                            "threshold_pct": -item.drop_pct_24h,
                        },
                        dedup_bucket=_bucket_hour(now, 1),
                        generated_at=now,
                    )
                )

        if item.rise_pct_24h is not None:
            window = trend.windows.get("24h")
            if window and window.change_pct is not None and window.change_pct >= item.rise_pct_24h:
                candidates.append(
                    Candidate(
                        goods_id=item.goods_id,
                        name=item.name,
                        kind="wishlist",
                        trigger="wishlist_rise",
                        reason=(
                            f"24h change {window.change_pct:.2f}% >= +{item.rise_pct_24h:.2f}%"
                        ),
                        metrics={
                            "sell_min_price": trend.latest_sell,
                            "change_pct_24h": window.change_pct,
                            "threshold_pct": item.rise_pct_24h,
                        },
                        dedup_bucket=_bucket_hour(now, 1),
                        generated_at=now,
                    )
                )

        if not candidates and self._needs_review(last_analysis, now):
            candidates.append(self._review_candidate(item, trend, now))
        return candidates

    def _needs_review(self, last_analysis: datetime | None, now: datetime) -> bool:
        if last_analysis is None:
            return True
        return (now - last_analysis) >= timedelta(days=self.wishlist_review_days)

    def _review_candidate(
        self,
        item: WishlistItem,
        trend: TrendSummary,
        now: datetime,
    ) -> Candidate:
        # Daily bucket so recurring review fires at most once per day.
        return Candidate(
            goods_id=item.goods_id,
            name=item.name,
            kind="wishlist",
            trigger="wishlist_review",
            reason=(
                f"periodic review (every {self.wishlist_review_days} days)"
            ),
            metrics={
                "sell_min_price": trend.latest_sell,
                "target_price": item.target_price,
                "drop_pct_24h": item.drop_pct_24h,
                "rise_pct_24h": item.rise_pct_24h,
            },
            dedup_bucket=_bucket_hour(now, 24),
            generated_at=now,
        )


def build_signal_snapshot(
    trend: TrendSummary,
    item: OwnedItem | WishlistItem,
) -> dict[str, object]:
    """Compact numeric summary passed to the LLM."""
    payload: dict[str, object] = {
        "goods_id": trend.goods_id,
        "as_of": trend.now.isoformat(),
        "latest_sell_min": trend.latest_sell,
        "latest_buy_max": trend.latest_buy,
        "coverage_ratio": round(trend.coverage_ratio, 3),
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
            for label, win in trend.windows.items()
        },
    }
    if isinstance(item, OwnedItem):
        payload["owned"] = {
            "purchase_price": item.purchase_price,
            "profit_pct": item.profit_pct,
            "loss_pct": item.loss_pct,
            "alert_above_price": item.alert_above_price,
        }
    else:
        payload["wishlist"] = {
            "target_price": item.target_price,
            "drop_pct_24h": item.drop_pct_24h,
        }
    return payload
