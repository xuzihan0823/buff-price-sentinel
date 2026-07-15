"""APScheduler-based long-running service."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
from datetime import datetime
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from buff_sentinel.service.pipeline import CollectionPipeline

LOG = logging.getLogger(__name__)


class ServiceRunner:
    """Runs the collection pipeline every `interval_seconds` with max_instances=1.

    A separate probe job calls `pipeline.probe_and_recover` at
    `probe_interval_seconds` so QQ outages are detected even when no new
    price alerts fire. Both jobs apply `schedule_jitter_seconds` to avoid
    lockstep cadence.
    """

    def __init__(
        self,
        *,
        pipeline: CollectionPipeline,
        interval_seconds: int,
        schedule_jitter_seconds: int = 30,
        probe_interval_seconds: int = 300,
    ) -> None:
        self.pipeline = pipeline
        self.interval_seconds = interval_seconds
        self.schedule_jitter_seconds = schedule_jitter_seconds
        self.probe_interval_seconds = probe_interval_seconds
        self._scheduler: AsyncIOScheduler | None = None
        self._stop_event = asyncio.Event()

    async def run_forever(self) -> None:
        self._scheduler = AsyncIOScheduler()
        self._scheduler.add_job(
            self._safe_tick,
            "interval",
            seconds=self.interval_seconds,
            jitter=self.schedule_jitter_seconds,
            id="collection",
            max_instances=1,
            coalesce=True,
            next_run_time=datetime.now(),
        )
        if self.probe_interval_seconds > 0:
            self._scheduler.add_job(
                self._safe_probe,
                "interval",
                seconds=self.probe_interval_seconds,
                jitter=self.schedule_jitter_seconds,
                id="qq_probe",
                max_instances=1,
                coalesce=True,
                next_run_time=None,
            )
        self._scheduler.start()
        LOG.info(
            "scheduler started interval=%ss jitter=%ss probe=%ss",
            self.interval_seconds,
            self.schedule_jitter_seconds,
            self.probe_interval_seconds or "disabled",
        )

        loop = asyncio.get_event_loop()
        for sig_name in ("SIGINT", "SIGTERM"):
            with contextlib.suppress(NotImplementedError, RuntimeError):
                loop.add_signal_handler(
                    getattr(signal, sig_name), self._request_stop
                )

        try:
            await self._stop_event.wait()
        finally:
            LOG.info("scheduler stopping")
            self._scheduler.shutdown(wait=False)

    def _request_stop(self, *_: Any) -> None:
        LOG.info("shutdown signal received")
        self._stop_event.set()

    async def _safe_tick(self) -> None:
        try:
            result = await self.pipeline.run_once()
            LOG.info("collection round result=%s", result.as_dict())
        except Exception:
            LOG.exception("collection round failed")

    async def _safe_probe(self) -> None:
        try:
            await self.pipeline.probe_and_recover()
        except Exception:
            LOG.exception("qq probe failed")
