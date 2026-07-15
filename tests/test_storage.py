from __future__ import annotations

from datetime import datetime, timedelta

from buff_sentinel.storage.repository import Repository, SnapshotInput, make_dedup_key


def _make_snap(
    goods_id: int,
    when: datetime,
    sell: float | None,
    buy: float | None,
) -> SnapshotInput:
    return SnapshotInput(
        goods_id=goods_id,
        captured_at=when,
        sell_min_price=sell,
        sell_reference_price=None,
        sell_listing_count=1 if sell is not None else None,
        buy_max_price=buy,
        buy_order_count=1 if buy is not None else None,
        partial=(sell is None or buy is None),
    )


def test_snapshot_all_null_rejected(repository: Repository) -> None:
    now = datetime.utcnow()
    result = repository.insert_snapshot(
        SnapshotInput(
            goods_id=1,
            captured_at=now,
            sell_min_price=None,
            sell_reference_price=None,
            sell_listing_count=None,
            buy_max_price=None,
            buy_order_count=None,
            partial=True,
        )
    )
    assert result is None


def test_snapshot_zero_price_stored_as_null(repository: Repository) -> None:
    now = datetime.utcnow()
    row = repository.insert_snapshot(
        SnapshotInput(
            goods_id=1,
            captured_at=now,
            sell_min_price=0,
            sell_reference_price=-5.0,
            sell_listing_count=3,
            buy_max_price=0,
            buy_order_count=2,
            partial=False,
        )
    )
    assert row is not None
    assert row.sell_min_price is None
    assert row.sell_reference_price is None
    assert row.buy_max_price is None
    assert row.sell_listing_count == 3


def test_alert_dedup_and_cooldown(repository: Repository) -> None:
    now = datetime.utcnow()
    row_a = repository.try_record_alert(
        goods_id=1,
        kind="owned",
        trigger="owned_profit",
        dedup_key=make_dedup_key([1, "owned_profit", "h1:1"]),
        fired_at=now,
        payload={"a": 1},
        cooldown=timedelta(minutes=60),
    )
    assert row_a is not None
    # Same window, same key -> deduped (cooldown blocks)
    row_b = repository.try_record_alert(
        goods_id=1,
        kind="owned",
        trigger="owned_profit",
        dedup_key=make_dedup_key([1, "owned_profit", "h1:1"]),
        fired_at=now + timedelta(minutes=5),
        payload={"a": 1},
        cooldown=timedelta(minutes=60),
    )
    assert row_b is None
    # Different trigger, but still same goods within cooldown -> blocked by cooldown.
    row_c = repository.try_record_alert(
        goods_id=1,
        kind="owned",
        trigger="owned_loss",
        dedup_key=make_dedup_key([1, "owned_loss", "h1:1"]),
        fired_at=now + timedelta(minutes=10),
        payload={"a": 1},
        cooldown=timedelta(minutes=60),
    )
    assert row_c is None
    # After cooldown elapsed, a new alert is allowed.
    row_d = repository.try_record_alert(
        goods_id=1,
        kind="owned",
        trigger="owned_profit",
        dedup_key=make_dedup_key([1, "owned_profit", "h1:99"]),
        fired_at=now + timedelta(hours=2),
        payload={"a": 1},
        cooldown=timedelta(minutes=60),
    )
    assert row_d is not None


def test_incident_lifecycle(repository: Repository) -> None:
    now = datetime.utcnow()
    inc = repository.open_incident(component="qq_bot", started_at=now, reason="network")
    # Reopening while active reuses the row and increments failure count.
    inc2 = repository.open_incident(component="qq_bot", started_at=now, reason="network")
    assert inc.id == inc2.id
    assert inc2.failure_count == 2
    repository.append_missed_alert(inc.id, {"goods_id": 1, "trigger": "owned_profit"})
    resolved = repository.resolve_incident(inc.id, now + timedelta(minutes=15))
    assert resolved is not None
    pending = repository.unresolved_summary_incidents()
    assert len(pending) == 1
    repository.mark_incident_summary_sent(pending[0].id)
    assert repository.unresolved_summary_incidents() == []


def test_prune_snapshots(repository: Repository) -> None:
    now = datetime.utcnow()
    repository.insert_snapshot(_make_snap(1, now - timedelta(days=10), 5.0, 4.0))
    repository.insert_snapshot(_make_snap(1, now, 6.0, 5.0))
    deleted = repository.prune_snapshots(now - timedelta(days=7))
    assert deleted == 1
    remaining = repository.snapshots_for(1, now - timedelta(days=30))
    assert len(remaining) == 1
