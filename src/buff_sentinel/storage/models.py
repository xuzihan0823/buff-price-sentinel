"""SQLAlchemy ORM models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base."""


class PriceSnapshot(Base):
    __tablename__ = "price_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    goods_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    sell_min_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    sell_reference_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    sell_listing_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    buy_max_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    buy_order_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    partial: Mapped[bool] = mapped_column(default=False, nullable=False)
    source: Mapped[str] = mapped_column(String(32), default="buff", nullable=False)

    __table_args__ = (
        Index("ix_price_snapshots_goods_time", "goods_id", "captured_at"),
    )


class AlertEvent(Base):
    __tablename__ = "alert_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    goods_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    trigger: Mapped[str] = mapped_column(String(64), nullable=False)
    dedup_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    fired_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    delivery_status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class LLMAnalysis(Base):
    __tablename__ = "llm_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    goods_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    prompt_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    response_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ServiceIncident(Base):
    __tablename__ = "service_incidents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    component: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    missed_alerts_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    summary_sent: Mapped[bool] = mapped_column(default=False, nullable=False)
