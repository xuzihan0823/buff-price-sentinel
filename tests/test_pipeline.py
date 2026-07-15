from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from buff_sentinel.buff.client import GoodsQuote
from buff_sentinel.config.schema import Config, OwnedItem
from buff_sentinel.llm.client import LLMAnalysisResult
from buff_sentinel.notifier.qq import QQSendResult
from buff_sentinel.service.pipeline import CollectionPipeline
from buff_sentinel.storage.database import Database
from buff_sentinel.storage.repository import Repository


class FakeBuff:
    def __init__(self, quotes: dict[int, GoodsQuote]) -> None:
        self.quotes = quotes
        self.calls: list[int] = []

    async def fetch_quote(self, goods_id: int) -> GoodsQuote:
        self.calls.append(goods_id)
        return self.quotes.get(
            goods_id,
            GoodsQuote(
                goods_id=goods_id,
                sell_min_price=100.0,
                sell_reference_price=None,
                sell_listing_count=1,
                buy_max_price=90.0,
                buy_order_count=1,
                partial=False,
            ),
        )

    async def aclose(self) -> None:
        return None


class FakeLLM:
    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.calls: list[dict[str, Any]] = []

    async def analyze(
        self,
        summary: dict[str, Any],
        *,
        item_kind: str,
        trigger: str,
    ) -> LLMAnalysisResult:
        self.calls.append({"summary": summary, "trigger": trigger, "kind": item_kind})
        if self.ok:
            return LLMAnalysisResult(
                ok=True,
                status="ok",
                model="fake",
                data={
                    "verdict": "sell",
                    "confidence": 0.75,
                    "risk": "medium",
                    "reasoning": "clear uptrend, take profits",
                    "suggested_action": "sell 50% today",
                },
                raw={"choices": []},
            )
        return LLMAnalysisResult(
            ok=False, status="invalid", model="fake", error="bad-json", raw={}
        )

    async def aclose(self) -> None:
        return None


class FakeQQ:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self.behavior: list[bool] = []  # queue of ok flags for send_c2c_text
        # Probe health: True = QQ reachable, False = outage. Can be a queue
        # (pop per probe call) or a single bool repeated forever.
        self.probe_results: list[bool] = [True]
        self.probe_calls: int = 0

    async def send_c2c_text(self, openid: str, text: str) -> QQSendResult:
        ok = self.behavior.pop(0) if self.behavior else True
        if ok:
            self.sent.append((openid, text))
            return QQSendResult(ok=True, openid=openid, status="sent")
        return QQSendResult(ok=False, openid=openid, status="error", detail="down")

    async def probe(self) -> bool:
        self.probe_calls += 1
        if len(self.probe_results) > 1:
            return self.probe_results.pop(0)
        return self.probe_results[0]

    async def aclose(self) -> None:
        return None


@dataclass
class _Env:
    pipeline: CollectionPipeline
    repo: Repository
    buff: FakeBuff
    llm: FakeLLM
    qq: FakeQQ
    now: datetime


def _build(config: Config, quotes: dict[int, GoodsQuote], now: datetime) -> _Env:
    db = Database("sqlite:///:memory:")
    db.create_all()
    repo = Repository(db)
    buff = FakeBuff(quotes)
    llm = FakeLLM(ok=True)
    qq = FakeQQ()
    pipeline = CollectionPipeline(
        config=config,
        repository=repo,
        buff_client=buff,  # type: ignore[arg-type]
        llm_client=llm,  # type: ignore[arg-type]
        qq_client=qq,  # type: ignore[arg-type]
        clock=lambda: now,
    )
    return _Env(pipeline=pipeline, repo=repo, buff=buff, llm=llm, qq=qq, now=now)


def _quote(goods_id: int, sell: float, buy: float | None = None) -> GoodsQuote:
    return GoodsQuote(
        goods_id=goods_id,
        sell_min_price=sell,
        sell_reference_price=None,
        sell_listing_count=1,
        buy_max_price=buy,
        buy_order_count=1 if buy is not None else None,
        partial=False,
    )


async def test_owned_profit_triggers_and_sends(sample_config: Config) -> None:
    now = datetime(2026, 7, 14, 12, 0, 0)
    env = _build(
        sample_config,
        quotes={
            762000: _quote(762000, 115.0, 110.0),  # 15% profit
            900000: _quote(900000, 500.0, 480.0),  # wishlist, no trigger
        },
        now=now,
    )
    result = await env.pipeline.run_once()
    assert result.snapshots_written == 10
    assert result.alerts_created >= 1
    assert result.alerts_sent >= 1
    assert env.qq.sent, "expected at least one QQ message"
    text = env.qq.sent[0][1]
    assert "owned_profit" in text
    assert "sell 50% today" in text  # from FakeLLM analysis


async def test_qq_outage_records_incident_and_recovery_summary(sample_config: Config) -> None:
    now = datetime(2026, 7, 14, 12, 0, 0)
    env = _build(
        sample_config,
        quotes={
            762000: _quote(762000, 115.0, 110.0),
            900000: _quote(900000, 500.0, 480.0),
        },
        now=now,
    )
    # QQ is down: alert sends fail and the probe also fails (outage persists).
    env.qq.behavior = [False, False]
    env.qq.probe_results = [False]
    result_a = await env.pipeline.run_once()
    assert result_a.alerts_failed >= 1
    incident = env.repo.active_incident("qq_bot")
    assert incident is not None
    assert incident.failure_count >= 1

    # Advance time; QQ recovers. Probe succeeds, incident resolves, and the
    # recovery summary is delivered.
    later = now + timedelta(hours=2)
    env.pipeline._clock = lambda: later  # type: ignore[method-assign]
    env.qq.behavior = []  # sends succeed
    env.qq.probe_results = [True]
    result_b = await env.pipeline.run_once()
    assert result_b.alerts_sent >= 1
    remaining = env.repo.unresolved_summary_incidents()
    assert remaining == []
    summary_texts = [t for _, t in env.qq.sent if "recovered" in t]
    assert summary_texts, "recovery summary must be sent after QQ comes back"


async def test_recovery_without_new_alerts(sample_config: Config) -> None:
    """Outage must recover even when no new price alerts fire."""
    now = datetime(2026, 7, 14, 12, 0, 0)
    # Keep this outage/recovery test focused on the probe path; periodic
    # wishlist review is covered separately below.
    sample_config.wishlist = []
    env = _build(
        sample_config,
        # Prices that trigger nothing (owned at cost, wishlist far from target).
        quotes={
            762000: _quote(762000, 100.0, 90.0),
            900000: _quote(900000, 500.0, 480.0),
        },
        now=now,
    )
    # Seed an open QQ incident manually (simulating a prior outage).
    inc = env.repo.open_incident(
        component="qq_bot", started_at=now - timedelta(hours=1), reason="prior outage"
    )
    env.repo.append_missed_alert(
        inc.id, {"goods_id": 762000, "name": "Owned Skin", "trigger": "owned_profit"}
    )

    # No alert candidates this round, but the probe runs and QQ is healthy.
    env.qq.probe_results = [True]
    env.qq.behavior = []
    result = await env.pipeline.run_once()
    assert result.candidates == 0
    assert result.alerts_created == 0
    assert result.probe_runs == 1
    assert result.probe_recovered == 1
    # Active incident is gone and the recovery summary was sent.
    assert env.repo.active_incident("qq_bot") is None
    assert env.repo.unresolved_summary_incidents() == []
    assert any("recovered" in t for _, t in env.qq.sent)


async def test_probe_failure_keeps_incident_open(sample_config: Config) -> None:
    """A failing probe must not resolve the incident or open a new one."""
    now = datetime(2026, 7, 14, 12, 0, 0)
    sample_config.wishlist = []
    env = _build(
        sample_config,
        quotes={
            762000: _quote(762000, 100.0, 90.0),
            900000: _quote(900000, 500.0, 480.0),
        },
        now=now,
    )
    env.repo.open_incident(
        component="qq_bot", started_at=now - timedelta(hours=1), reason="outage"
    )
    env.qq.probe_results = [False]
    result = await env.pipeline.run_once()
    assert result.probe_recovered == 0
    assert env.repo.active_incident("qq_bot") is not None
    # No new incident rows created.
    assert result.alerts_created == 0


async def test_dry_run_skips_llm_qq_and_dedup(sample_config: Config) -> None:
    now = datetime(2026, 7, 14, 12, 0, 0)
    env = _build(
        sample_config,
        quotes={
            762000: _quote(762000, 115.0, 110.0),  # would trigger owned_profit
            900000: _quote(900000, 500.0, 480.0),
        },
        now=now,
    )
    result = await env.pipeline.run_once(dry_run=True)
    assert result.dry_run is True
    assert result.snapshots_written == 10
    assert result.candidates >= 1
    assert result.candidates_detail, "dry-run must list candidates"
    assert result.candidates_detail[0]["trigger"] == "owned_profit"
    # No alert/LLM/QQ side effects.
    assert result.alerts_created == 0
    assert result.llm_ok == 0
    assert env.llm.calls == []
    assert env.qq.sent == []
    # Dedup state untouched: a subsequent real run still creates the alert.
    real = await env.pipeline.run_once(dry_run=False)
    assert real.alerts_created >= 1


async def test_owned_above_price_crosses_once(sample_config: Config) -> None:
    now = datetime(2026, 7, 14, 12, 0, 0)
    sample_config.owned = [
        OwnedItem(
            goods_id=872000,
            name="Butterfly Knife",
            purchase_price=4150.0,
            alert_above_price=4000.0,
        )
    ]
    sample_config.wishlist = []
    env = _build(
        sample_config,
        quotes={872000: _quote(872000, 3795.0, 3700.0)},
        now=now,
    )

    baseline = await env.pipeline.run_once()
    assert baseline.candidates == 0

    later = now + timedelta(minutes=10)
    env.pipeline._clock = lambda: later  # type: ignore[method-assign]
    env.buff.quotes[872000] = _quote(872000, 4010.0, 3900.0)
    crossed = await env.pipeline.run_once()
    assert crossed.alerts_created == 1
    assert crossed.alerts_sent == 1

    still_above = later + timedelta(hours=2)
    env.pipeline._clock = lambda: still_above  # type: ignore[method-assign]
    env.buff.quotes[872000] = _quote(872000, 4020.0, 3910.0)
    repeated = await env.pipeline.run_once()
    assert repeated.candidates == 0
    assert repeated.alerts_created == 0


async def test_wishlist_review_reuses_dedup_bucket(sample_config: Config) -> None:
    now = datetime(2026, 7, 14, 12, 0, 0)
    # Force wishlist to only satisfy periodic review.
    sample_config.wishlist[0].target_price = 1.0
    sample_config.wishlist[0].drop_pct_24h = 999.0
    env = _build(
        sample_config,
        quotes={
            762000: _quote(762000, 100.0, 90.0),  # owned at cost, no trigger
            900000: _quote(900000, 500.0, 480.0),
        },
        now=now,
    )
    # No prior analysis exists -> review candidate should fire once.
    result_a = await env.pipeline.run_once()
    assert result_a.alerts_created >= 1
    # Immediate re-run: dedup bucket + cooldown should suppress duplicate alert.
    result_b = await env.pipeline.run_once()
    assert result_b.alerts_created == 0
