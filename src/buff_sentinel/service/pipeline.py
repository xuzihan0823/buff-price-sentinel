"""Collection + evaluation pipeline used by scheduler and CLI."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from buff_sentinel.analytics.rules import (
    Candidate,
    RuleEngine,
    build_signal_snapshot,
)
from buff_sentinel.analytics.trends import compute_trends
from buff_sentinel.buff.client import BuffClient, GoodsQuote
from buff_sentinel.config.schema import Config, OwnedItem, WishlistItem
from buff_sentinel.llm.client import LLMClient
from buff_sentinel.notifier.formatter import (
    format_alert_text,
    format_recovery_summary,
)
from buff_sentinel.notifier.qq import QQBotClient
from buff_sentinel.storage.repository import (
    Repository,
    SnapshotInput,
    make_dedup_key,
    utcnow,
)

LOG = logging.getLogger(__name__)


@dataclass(slots=True)
class PipelineResult:
    started_at: datetime
    finished_at: datetime
    dry_run: bool = False
    quotes_ok: int = 0
    quotes_partial: int = 0
    quotes_failed: int = 0
    snapshots_written: int = 0
    candidates: int = 0
    candidates_detail: list[dict[str, Any]] = field(default_factory=list)
    alerts_created: int = 0
    alerts_sent: int = 0
    alerts_failed: int = 0
    llm_ok: int = 0
    llm_failed: int = 0
    probe_runs: int = 0
    probe_recovered: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "dry_run": self.dry_run,
            "quotes_ok": self.quotes_ok,
            "quotes_partial": self.quotes_partial,
            "quotes_failed": self.quotes_failed,
            "snapshots_written": self.snapshots_written,
            "candidates": self.candidates,
            "candidates_detail": list(self.candidates_detail),
            "alerts_created": self.alerts_created,
            "alerts_sent": self.alerts_sent,
            "alerts_failed": self.alerts_failed,
            "llm_ok": self.llm_ok,
            "llm_failed": self.llm_failed,
            "probe_runs": self.probe_runs,
            "probe_recovered": self.probe_recovered,
            "errors": list(self.errors),
        }


class CollectionPipeline:
    """One collection round: fetch, persist, evaluate, notify."""

    def __init__(
        self,
        *,
        config: Config,
        repository: Repository,
        buff_client: BuffClient,
        llm_client: LLMClient,
        qq_client: QQBotClient,
        rule_engine: RuleEngine | None = None,
        clock: Any = None,
    ) -> None:
        self.config = config
        self.repository = repository
        self.buff = buff_client
        self.llm = llm_client
        self.qq = qq_client
        self.rule_engine = rule_engine or RuleEngine(
            wishlist_review_days=config.collection.wishlist_review_days
        )
        self._clock = clock or utcnow

    async def run_once(self, *, dry_run: bool = False) -> PipelineResult:
        started = self._clock()
        result = PipelineResult(started_at=started, finished_at=started, dry_run=dry_run)
        try:
            await self._run_body(result, dry_run=dry_run)
        finally:
            result.finished_at = self._clock()
            self._prune_history(result.finished_at)
        return result

    async def _run_body(self, result: PipelineResult, *, dry_run: bool) -> None:
        items: list[OwnedItem | WishlistItem] = [
            *self.config.owned,
            *self.config.wishlist,
        ]
        quotes = await self._collect_quotes(items, result)
        self._persist_snapshots(quotes, result)
        candidates = self._evaluate_rules(items, quotes, result)
        if dry_run:
            result.candidates_detail = [
                {
                    "goods_id": c.goods_id,
                    "name": c.name,
                    "kind": c.kind,
                    "trigger": c.trigger,
                    "reason": c.reason,
                    "metrics": c.metrics,
                    "generated_at": c.generated_at.isoformat(),
                }
                for _item, c in candidates
            ]
            # Dry-run must not touch LLM/QQ or mutate alert dedup state.
            LOG.info("dry-run: %s candidate(s) evaluated, no alerts sent", len(candidates))
            return
        await self._deliver_alerts(items, candidates, quotes, result)
        await self.probe_and_recover(result)

    async def probe_and_recover(self, result: PipelineResult | None = None) -> None:
        """Independent recovery probe.

        If a QQ incident is active, send a lightweight probe. On success,
        resolve the incident, then attempt to deliver any pending recovery
        summaries. A failed recovery-summary delivery must NOT open a new
        incident (it simply stays unsent and is retried on the next probe).
        """
        if result is None:
            result = PipelineResult(
                started_at=self._clock(), finished_at=self._clock()
            )
        active = self.repository.active_incident("qq_bot")
        result.probe_runs += 1
        if active is not None:
            healthy = await self.qq.probe()
            if healthy:
                resolved = self.repository.resolve_incident(active.id, self._clock())
                if resolved is not None:
                    result.probe_recovered += 1
                    LOG.info(
                        "qq probe recovered incident id=%s failures=%s",
                        active.id, active.failure_count,
                    )
            else:
                LOG.info("qq probe still unhealthy; incident stays open")
        # Always attempt pending recovery summaries (resolved but unsent).
        await self._handle_recovery_summary(result)

    async def _collect_quotes(
        self,
        items: list[OwnedItem | WishlistItem],
        result: PipelineResult,
    ) -> dict[int, GoodsQuote]:
        async def _one(item: OwnedItem | WishlistItem) -> tuple[int, GoodsQuote | None]:
            try:
                quote = await self.buff.fetch_quote(item.goods_id)
                return item.goods_id, quote
            except Exception as exc:  # pragma: no cover - unexpected
                LOG.exception("buff quote failed goods_id=%s", item.goods_id)
                result.errors.append(f"buff:{item.goods_id}:{exc}")
                return item.goods_id, None

        gathered = await asyncio.gather(*(_one(item) for item in items))
        quotes: dict[int, GoodsQuote] = {}
        for goods_id, quote in gathered:
            if quote is None:
                result.quotes_failed += 1
                continue
            if not quote.usable:
                result.quotes_failed += 1
                continue
            quotes[goods_id] = quote
            if quote.partial:
                result.quotes_partial += 1
            else:
                result.quotes_ok += 1
        return quotes

    def _persist_snapshots(
        self,
        quotes: dict[int, GoodsQuote],
        result: PipelineResult,
    ) -> None:
        now = self._clock()
        for goods_id, quote in quotes.items():
            snap = SnapshotInput(
                goods_id=goods_id,
                captured_at=now,
                sell_min_price=quote.sell_min_price,
                sell_reference_price=quote.sell_reference_price,
                sell_listing_count=quote.sell_listing_count,
                buy_max_price=quote.buy_max_price,
                buy_order_count=quote.buy_order_count,
                partial=quote.partial,
            )
            row = self.repository.insert_snapshot(snap)
            if row is not None:
                result.snapshots_written += 1
        cutoff = now - timedelta(days=self.config.collection.snapshot_retention_days)
        self.repository.prune_snapshots(cutoff)

    def _evaluate_rules(
        self,
        items: list[OwnedItem | WishlistItem],
        quotes: dict[int, GoodsQuote],
        result: PipelineResult,
    ) -> list[tuple[OwnedItem | WishlistItem, Candidate]]:
        now = self._clock()
        seven_days_ago = now - timedelta(days=7)
        emitted: list[tuple[OwnedItem | WishlistItem, Candidate]] = []
        for item in items:
            if item.goods_id not in quotes:
                # Still fire periodic review for wishlist if past interval.
                if isinstance(item, WishlistItem):
                    last = self.repository.last_analysis_at(item.goods_id)
                    if self.rule_engine._needs_review(last, now):
                        snapshots = self.repository.snapshots_for(item.goods_id, seven_days_ago)
                        trend = compute_trends(item.goods_id, snapshots, now)
                        cands = self.rule_engine.evaluate_wishlist(item, trend, now, last)
                        for c in cands:
                            emitted.append((item, c))
                continue
            snapshots = self.repository.snapshots_for(item.goods_id, seven_days_ago)
            trend = compute_trends(item.goods_id, snapshots, now)
            if isinstance(item, OwnedItem):
                for c in self.rule_engine.evaluate_owned(item, trend, now):
                    emitted.append((item, c))
            else:
                last = self.repository.last_analysis_at(item.goods_id)
                for c in self.rule_engine.evaluate_wishlist(item, trend, now, last):
                    emitted.append((item, c))
        result.candidates = len(emitted)
        return emitted

    async def _deliver_alerts(
        self,
        items: list[OwnedItem | WishlistItem],
        emitted: list[tuple[OwnedItem | WishlistItem, Candidate]],
        quotes: dict[int, GoodsQuote],
        result: PipelineResult,
    ) -> None:
        if not emitted:
            return
        cooldown = timedelta(minutes=self.config.alerts.goods_cooldown_minutes)
        now = self._clock()
        seven_days_ago = now - timedelta(days=7)
        for item, candidate in emitted:
            dedup_key = make_dedup_key(
                [
                    str(candidate.goods_id),
                    candidate.trigger,
                    candidate.dedup_bucket,
                ]
            )
            payload: dict[str, Any] = {
                "trigger": candidate.trigger,
                "kind": candidate.kind,
                "reason": candidate.reason,
                "metrics": candidate.metrics,
                "name": candidate.name,
            }
            row = self.repository.try_record_alert(
                goods_id=candidate.goods_id,
                kind=candidate.kind,
                trigger=candidate.trigger,
                dedup_key=dedup_key,
                fired_at=candidate.generated_at,
                payload=payload,
                cooldown=cooldown,
            )
            if row is None:
                LOG.info(
                    "alert deduped goods_id=%s trigger=%s",
                    candidate.goods_id, candidate.trigger,
                )
                continue
            result.alerts_created += 1

            analysis_data: dict[str, Any] | None = None
            snapshots = self.repository.snapshots_for(candidate.goods_id, seven_days_ago)
            trend = compute_trends(candidate.goods_id, snapshots, now)
            summary = build_signal_snapshot(trend, item)

            llm_result = await self.llm.analyze(
                summary,
                item_kind=candidate.kind,
                trigger=candidate.trigger,
            )
            self.repository.record_analysis(
                goods_id=candidate.goods_id,
                kind=candidate.kind,
                analyzed_at=self._clock(),
                status=llm_result.status,
                model=llm_result.model,
                prompt=summary,
                response=llm_result.raw,
                error=llm_result.error,
            )
            if llm_result.ok and llm_result.data:
                analysis_data = llm_result.data
                result.llm_ok += 1
            else:
                result.llm_failed += 1

            text = format_alert_text(
                name=candidate.name,
                goods_id=candidate.goods_id,
                trigger=candidate.trigger,
                reason=candidate.reason,
                metrics=candidate.metrics,
                analysis=analysis_data,
                generated_at=candidate.generated_at,
            )

            payload["text"] = text
            payload["analysis"] = analysis_data
            all_ok = True
            first_error: str | None = None
            for openid in self.config.qq_bot.recipients:
                send_result = await self.qq.send_c2c_text(openid, text)
                if not send_result.ok:
                    all_ok = False
                    first_error = first_error or send_result.detail
            if all_ok:
                self.repository.mark_alert_delivered(row.id, self._clock())
                result.alerts_sent += 1
                self._resolve_incident(now)
            else:
                self.repository.mark_alert_failed(row.id, first_error or "unknown")
                result.alerts_failed += 1
                self._track_incident(row.id, candidate, first_error or "unknown", now)

    def _track_incident(
        self,
        alert_id: int,
        candidate: Candidate,
        error: str,
        now: datetime,
    ) -> None:
        incident = self.repository.open_incident(
            component="qq_bot",
            started_at=now,
            reason=error,
        )
        entry = {
            "alert_id": alert_id,
            "goods_id": candidate.goods_id,
            "name": candidate.name,
            "trigger": candidate.trigger,
            "fired_at": candidate.generated_at.isoformat(),
        }
        self.repository.append_missed_alert(incident.id, entry)

    def _resolve_incident(self, now: datetime) -> None:
        active = self.repository.active_incident("qq_bot")
        if active is not None:
            self.repository.resolve_incident(active.id, now)

    async def _handle_recovery_summary(self, result: PipelineResult) -> None:
        pending = self.repository.unresolved_summary_incidents()
        if not pending:
            return
        for incident in pending:
            missed = json.loads(incident.missed_alerts_json or "[]")
            if incident.resolved_at is None:
                continue
            text = format_recovery_summary(
                started_at=incident.started_at,
                resolved_at=incident.resolved_at,
                failure_count=incident.failure_count,
                missed_alerts=missed,
            )
            delivered = True
            for openid in self.config.qq_bot.recipients:
                res = await self.qq.send_c2c_text(openid, text)
                if not res.ok:
                    delivered = False
                    break
            if delivered:
                self.repository.mark_incident_summary_sent(incident.id)
                result.alerts_sent += 1
            else:
                # Leave summary_sent=False so the next probe retries. Do NOT
                # open a new incident: the outage itself is already resolved.
                LOG.warning(
                    "recovery summary delivery failed for incident %s; "
                    "will retry on next probe",
                    incident.id,
                )

    def _prune_history(self, now: datetime) -> None:
        older_than = now - timedelta(
            days=self.config.collection.history_retention_days
        )
        try:
            self.repository.prune_history(older_than)
        except Exception:  # pragma: no cover - non-critical maintenance
            LOG.exception("history prune failed")


def now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
