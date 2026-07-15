from __future__ import annotations

from datetime import datetime, timedelta

from buff_sentinel.analytics.rules import RuleEngine
from buff_sentinel.analytics.trends import compute_trends
from buff_sentinel.config.schema import OwnedItem, WishlistItem
from buff_sentinel.storage.models import PriceSnapshot


def _snap(
    goods_id: int,
    when: datetime,
    sell: float | None,
    buy: float | None = None,
) -> PriceSnapshot:
    return PriceSnapshot(
        goods_id=goods_id,
        captured_at=when,
        sell_min_price=sell,
        buy_max_price=buy,
        sell_listing_count=1 if sell is not None else None,
        buy_order_count=1 if buy is not None else None,
    )


def test_trend_windows_cover_multiple_ranges() -> None:
    now = datetime(2026, 7, 14, 12, 0, 0)
    snaps = [
        _snap(1, now - timedelta(days=6, hours=12), 100.0),
        _snap(1, now - timedelta(days=3), 90.0),
        _snap(1, now - timedelta(hours=23), 95.0),
        _snap(1, now - timedelta(hours=5), 92.0),
        _snap(1, now - timedelta(minutes=30), 88.0),
    ]
    trend = compute_trends(1, snaps, now)
    assert trend.latest_sell == 88.0
    windows = trend.windows
    assert windows["24h"].samples == 3
    assert windows["24h"].first == 95.0
    assert windows["24h"].last == 88.0
    assert windows["7d"].samples == 5
    assert 0 < trend.coverage_ratio <= 1.0


def test_owned_profit_trigger_fires_and_loss_ignored() -> None:
    now = datetime(2026, 7, 14, 12, 0, 0)
    item = OwnedItem(
        goods_id=1,
        name="Test",
        purchase_price=100.0,
        profit_pct=10.0,
        loss_pct=10.0,
    )
    snaps = [_snap(1, now - timedelta(minutes=5), 120.0)]
    trend = compute_trends(1, snaps, now)
    engine = RuleEngine(wishlist_review_days=3)
    candidates = engine.evaluate_owned(item, trend, now)
    assert len(candidates) == 1
    assert candidates[0].trigger == "owned_profit"


def test_owned_loss_trigger() -> None:
    now = datetime(2026, 7, 14, 12, 0, 0)
    item = OwnedItem(
        goods_id=1,
        name="Test",
        purchase_price=100.0,
        profit_pct=10.0,
        loss_pct=8.0,
    )
    snaps = [_snap(1, now - timedelta(minutes=1), 91.0)]
    trend = compute_trends(1, snaps, now)
    candidates = RuleEngine().evaluate_owned(item, trend, now)
    assert len(candidates) == 1
    assert candidates[0].trigger == "owned_loss"


def test_wishlist_floor_and_drop_triggers() -> None:
    now = datetime(2026, 7, 14, 12, 0, 0)
    item = WishlistItem(
        goods_id=2,
        name="W",
        target_price=100.0,
        drop_pct_24h=10.0,
    )
    snaps = [
        _snap(2, now - timedelta(hours=23), 120.0),
        _snap(2, now - timedelta(minutes=1), 95.0),
    ]
    trend = compute_trends(2, snaps, now)
    candidates = RuleEngine().evaluate_wishlist(item, trend, now, last_analysis=now)
    triggers = {c.trigger for c in candidates}
    assert "wishlist_floor" in triggers
    assert "wishlist_drop" in triggers


def test_wishlist_periodic_review_fires_when_nothing_else() -> None:
    now = datetime(2026, 7, 14, 12, 0, 0)
    item = WishlistItem(goods_id=3, name="W", target_price=1.0)  # never triggers
    snaps = [_snap(3, now - timedelta(minutes=1), 500.0)]
    trend = compute_trends(3, snaps, now)
    engine = RuleEngine(wishlist_review_days=3)
    last = now - timedelta(days=4)
    candidates = engine.evaluate_wishlist(item, trend, now, last_analysis=last)
    assert len(candidates) == 1
    assert candidates[0].trigger == "wishlist_review"


def test_wishlist_review_skipped_within_window() -> None:
    now = datetime(2026, 7, 14, 12, 0, 0)
    item = WishlistItem(goods_id=3, name="W", target_price=1.0)
    snaps = [_snap(3, now - timedelta(minutes=1), 500.0)]
    trend = compute_trends(3, snaps, now)
    engine = RuleEngine(wishlist_review_days=3)
    last = now - timedelta(days=1)
    candidates = engine.evaluate_wishlist(item, trend, now, last_analysis=last)
    assert candidates == []


def test_wishlist_review_when_price_missing() -> None:
    now = datetime(2026, 7, 14, 12, 0, 0)
    item = WishlistItem(goods_id=3, name="W", target_price=1.0)
    trend = compute_trends(3, [], now)
    engine = RuleEngine(wishlist_review_days=3)
    candidates = engine.evaluate_wishlist(item, trend, now, last_analysis=None)
    assert len(candidates) == 1
    assert candidates[0].trigger == "wishlist_review"
