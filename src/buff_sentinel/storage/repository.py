"""Repository operations over the ORM models."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from buff_sentinel.storage.database import Database
from buff_sentinel.storage.models import (
    AlertEvent,
    LLMAnalysis,
    PriceSnapshot,
    ServiceIncident,
)


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@dataclass(slots=True)
class SnapshotInput:
    goods_id: int
    captured_at: datetime
    sell_min_price: float | None
    sell_reference_price: float | None
    sell_listing_count: int | None
    buy_max_price: float | None
    buy_order_count: int | None
    partial: bool


class Repository:
    """High-level persistence surface."""

    def __init__(self, database: Database) -> None:
        self.db = database

    # ---------------------------------------------------------------- snapshots
    def insert_snapshot(self, snap: SnapshotInput) -> PriceSnapshot | None:
        # Refuse to record all-null rows; nothing useful was captured.
        if (
            snap.sell_min_price is None
            and snap.buy_max_price is None
            and snap.sell_listing_count is None
            and snap.buy_order_count is None
        ):
            return None
        # Never coerce failed prices to zero: values <= 0 are discarded.
        sell_min = snap.sell_min_price if _is_positive(snap.sell_min_price) else None
        sell_ref = (
            snap.sell_reference_price if _is_positive(snap.sell_reference_price) else None
        )
        buy_max = snap.buy_max_price if _is_positive(snap.buy_max_price) else None
        with self.db.session() as session:
            row = PriceSnapshot(
                goods_id=snap.goods_id,
                captured_at=snap.captured_at,
                sell_min_price=sell_min,
                sell_reference_price=sell_ref,
                sell_listing_count=snap.sell_listing_count,
                buy_max_price=buy_max,
                buy_order_count=snap.buy_order_count,
                partial=snap.partial,
                source="buff",
            )
            session.add(row)
            session.flush()
            session.refresh(row)
            return row

    def snapshots_for(
        self,
        goods_id: int,
        since: datetime,
        until: datetime | None = None,
    ) -> list[PriceSnapshot]:
        stmt = select(PriceSnapshot).where(
            PriceSnapshot.goods_id == goods_id,
            PriceSnapshot.captured_at >= since,
        )
        if until is not None:
            stmt = stmt.where(PriceSnapshot.captured_at <= until)
        stmt = stmt.order_by(PriceSnapshot.captured_at.asc())
        with self.db.session() as session:
            return list(session.scalars(stmt))

    def latest_snapshot(self, goods_id: int) -> PriceSnapshot | None:
        stmt = (
            select(PriceSnapshot)
            .where(PriceSnapshot.goods_id == goods_id)
            .order_by(PriceSnapshot.captured_at.desc())
            .limit(1)
        )
        with self.db.session() as session:
            return session.scalars(stmt).first()

    def prune_snapshots(self, older_than: datetime) -> int:
        stmt = delete(PriceSnapshot).where(PriceSnapshot.captured_at < older_than)
        with self.db.session() as session:
            result = session.execute(stmt)
            return int(getattr(result, "rowcount", 0) or 0)

    # ---------------------------------------------------------------- alerts
    def try_record_alert(
        self,
        *,
        goods_id: int,
        kind: str,
        trigger: str,
        dedup_key: str,
        fired_at: datetime,
        payload: dict[str, Any],
        cooldown: timedelta,
    ) -> AlertEvent | None:
        """Insert an alert row iff dedup key is fresh and cooldown is honored."""
        with self.db.session() as session:
            recent = session.scalars(
                select(AlertEvent)
                .where(
                    AlertEvent.goods_id == goods_id,
                    AlertEvent.fired_at >= fired_at - cooldown,
                )
                .order_by(AlertEvent.fired_at.desc())
                .limit(1)
            ).first()
            if recent is not None:
                return None
            row = AlertEvent(
                goods_id=goods_id,
                kind=kind,
                trigger=trigger,
                dedup_key=dedup_key,
                fired_at=fired_at,
                payload_json=json.dumps(payload, ensure_ascii=False, sort_keys=True),
                delivery_status="pending",
            )
            session.add(row)
            try:
                session.flush()
            except IntegrityError:
                session.rollback()
                return None
            session.refresh(row)
            return row

    def mark_alert_delivered(self, alert_id: int, when: datetime) -> None:
        with self.db.session() as session:
            row = session.get(AlertEvent, alert_id)
            if row is None:
                return
            row.delivery_status = "sent"
            row.sent_at = when
            row.error = None

    def mark_alert_failed(self, alert_id: int, error: str) -> None:
        with self.db.session() as session:
            row = session.get(AlertEvent, alert_id)
            if row is None:
                return
            row.delivery_status = "failed"
            row.error = error[:1000]

    def pending_alerts(self, limit: int = 50) -> list[AlertEvent]:
        stmt = (
            select(AlertEvent)
            .where(AlertEvent.delivery_status.in_(["pending", "failed"]))
            .order_by(AlertEvent.fired_at.asc())
            .limit(limit)
        )
        with self.db.session() as session:
            return list(session.scalars(stmt))

    def last_analysis_at(self, goods_id: int) -> datetime | None:
        stmt = (
            select(LLMAnalysis.analyzed_at)
            .where(LLMAnalysis.goods_id == goods_id)
            .order_by(LLMAnalysis.analyzed_at.desc())
            .limit(1)
        )
        with self.db.session() as session:
            return session.scalars(stmt).first()

    # ---------------------------------------------------------------- llm log
    def record_analysis(
        self,
        *,
        goods_id: int,
        kind: str,
        analyzed_at: datetime,
        status: str,
        model: str,
        prompt: dict[str, Any],
        response: dict[str, Any] | None,
        error: str | None,
    ) -> LLMAnalysis:
        with self.db.session() as session:
            row = LLMAnalysis(
                goods_id=goods_id,
                kind=kind,
                analyzed_at=analyzed_at,
                status=status,
                model=model,
                prompt_json=json.dumps(prompt, ensure_ascii=False, sort_keys=True),
                response_json=json.dumps(
                    response or {}, ensure_ascii=False, sort_keys=True
                ),
                error=(error or None),
            )
            session.add(row)
            session.flush()
            session.refresh(row)
            return row

    # ---------------------------------------------------------------- incidents
    def open_incident(
        self,
        *,
        component: str,
        started_at: datetime,
        reason: str,
    ) -> ServiceIncident:
        with self.db.session() as session:
            existing = session.scalars(
                select(ServiceIncident)
                .where(
                    ServiceIncident.component == component,
                    ServiceIncident.resolved_at.is_(None),
                )
                .limit(1)
            ).first()
            if existing is not None:
                existing.failure_count += 1
                existing.reason = reason[:1000]
                session.flush()
                session.refresh(existing)
                return existing
            row = ServiceIncident(
                component=component,
                started_at=started_at,
                reason=reason[:1000],
                failure_count=1,
                missed_alerts_json="[]",
                summary_sent=False,
            )
            session.add(row)
            session.flush()
            session.refresh(row)
            return row

    def append_missed_alert(self, incident_id: int, entry: dict[str, Any]) -> None:
        with self.db.session() as session:
            row = session.get(ServiceIncident, incident_id)
            if row is None:
                return
            missed = json.loads(row.missed_alerts_json or "[]")
            missed.append(entry)
            row.missed_alerts_json = json.dumps(missed, ensure_ascii=False)

    def active_incident(self, component: str) -> ServiceIncident | None:
        stmt = (
            select(ServiceIncident)
            .where(
                ServiceIncident.component == component,
                ServiceIncident.resolved_at.is_(None),
            )
            .order_by(ServiceIncident.started_at.desc())
            .limit(1)
        )
        with self.db.session() as session:
            return session.scalars(stmt).first()

    def resolve_incident(
        self, incident_id: int, resolved_at: datetime
    ) -> ServiceIncident | None:
        with self.db.session() as session:
            row = session.get(ServiceIncident, incident_id)
            if row is None or row.resolved_at is not None:
                return row
            row.resolved_at = resolved_at
            session.flush()
            session.refresh(row)
            return row

    def mark_incident_summary_sent(self, incident_id: int) -> None:
        with self.db.session() as session:
            row = session.get(ServiceIncident, incident_id)
            if row is not None:
                row.summary_sent = True

    def unresolved_summary_incidents(self) -> list[ServiceIncident]:
        stmt = (
            select(ServiceIncident)
            .where(
                ServiceIncident.resolved_at.is_not(None),
                ServiceIncident.summary_sent.is_(False),
            )
            .order_by(ServiceIncident.started_at.asc())
        )
        with self.db.session() as session:
            return list(session.scalars(stmt))

    def prune_history(self, older_than: datetime) -> dict[str, int]:
        deletes = {
            "alerts": delete(AlertEvent).where(AlertEvent.fired_at < older_than),
            "analyses": delete(LLMAnalysis).where(LLMAnalysis.analyzed_at < older_than),
            "incidents": delete(ServiceIncident).where(
                ServiceIncident.resolved_at.is_not(None),
                ServiceIncident.started_at < older_than,
            ),
        }
        counts: dict[str, int] = {}
        with self.db.session() as session:
            for name, stmt in deletes.items():
                result = session.execute(stmt)
                counts[name] = int(getattr(result, "rowcount", 0) or 0)
        return counts


def _is_positive(value: float | None) -> bool:
    return value is not None and value > 0


def make_dedup_key(parts: Iterable[str]) -> str:
    return "|".join(str(p) for p in parts)
