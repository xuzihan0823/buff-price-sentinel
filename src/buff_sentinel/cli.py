"""CLI entrypoints."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import sys
from typing import Any

import typer

from buff_sentinel.buff.client import BuffClient
from buff_sentinel.config import ConfigError, load_config_any
from buff_sentinel.config.schema import Config
from buff_sentinel.llm.client import LLMClient
from buff_sentinel.logging_setup import configure_logging
from buff_sentinel.notifier.qq import QQBotClient
from buff_sentinel.service.pipeline import CollectionPipeline
from buff_sentinel.service.scheduler import ServiceRunner
from buff_sentinel.storage.database import Database
from buff_sentinel.storage.repository import Repository, utcnow

LOG = logging.getLogger(__name__)
app = typer.Typer(help="BUFF Price Sentinel CLI", add_completion=False)


def _default_config_path() -> str:
    return os.environ.get("BUFF_SENTINEL_CONFIG") or "config.yaml"


def _default_config_dir() -> str | None:
    return os.environ.get("BUFF_SENTINEL_CONFIG_DIR")


def _load(
    config_path: str | None, config_dir: str | None
) -> Config:
    cdir = config_dir or _default_config_dir()
    path = config_path or _default_config_path()
    try:
        if cdir:
            return load_config_any(None, config_dir=cdir)
        return load_config_any(path, config_dir=None)
    except ConfigError as exc:
        typer.echo(f"config error: {exc}", err=True)
        raise typer.Exit(code=2) from exc


def _build_pipeline(
    config: Config, database: Database
) -> tuple[CollectionPipeline, BuffClient, LLMClient, QQBotClient]:
    buff = BuffClient(config.buff)
    llm = LLMClient(config.llm)
    qq = QQBotClient(config.qq_bot)
    repo = Repository(database)
    pipeline = CollectionPipeline(
        config=config,
        repository=repo,
        buff_client=buff,
        llm_client=llm,
        qq_client=qq,
    )
    return pipeline, buff, llm, qq


@app.command()
def validate_config(
    config_path: str | None = typer.Option(None, "--config", "-c"),
    config_dir: str | None = typer.Option(None, "--config-dir"),
) -> None:
    """Load and validate the config, printing the resolved summary."""
    cfg = _load(config_path, config_dir)
    summary = {
        "owned": len(cfg.owned),
        "wishlist": len(cfg.wishlist),
        "interval_seconds": cfg.collection.interval_seconds,
        "schedule_jitter_seconds": cfg.collection.schedule_jitter_seconds,
        "probe_interval_seconds": cfg.collection.probe_interval_seconds,
        "database_url": cfg.app.database_url,
        "timezone": cfg.app.timezone,
        "llm_model_id": cfg.llm.model_id,
        "qq_recipients": len(cfg.qq_bot.recipients),
    }
    typer.echo(json.dumps(summary, indent=2))


@app.command()
def once(
    config_path: str | None = typer.Option(None, "--config", "-c"),
    config_dir: str | None = typer.Option(None, "--config-dir"),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Collect/evaluate but skip LLM, QQ, and alert dedup writes.",
    ),
) -> None:
    """Run one collection round and exit."""
    cfg = _load(config_path, config_dir)
    configure_logging(cfg.app.log_level)
    database = Database(cfg.app.database_url)
    database.create_all()
    pipeline, buff, llm, qq = _build_pipeline(cfg, database)

    async def _run() -> None:
        try:
            result = await pipeline.run_once(dry_run=dry_run)
            typer.echo(json.dumps(result.as_dict(), indent=2))
        finally:
            await buff.aclose()
            await llm.aclose()
            await qq.aclose()

    asyncio.run(_run())


@app.command("run")
def run_forever(
    config_path: str | None = typer.Option(None, "--config", "-c"),
    config_dir: str | None = typer.Option(None, "--config-dir"),
) -> None:
    """Run the scheduler daemon."""
    cfg = _load(config_path, config_dir)
    configure_logging(cfg.app.log_level)
    database = Database(cfg.app.database_url)
    database.create_all()
    pipeline, buff, llm, qq = _build_pipeline(cfg, database)
    runner = ServiceRunner(
        pipeline=pipeline,
        interval_seconds=cfg.collection.interval_seconds,
        schedule_jitter_seconds=cfg.collection.schedule_jitter_seconds,
        probe_interval_seconds=cfg.collection.probe_interval_seconds,
    )

    async def _run() -> None:
        try:
            await runner.run_forever()
        finally:
            await buff.aclose()
            await llm.aclose()
            await qq.aclose()

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_run())


@app.command()
def probe(
    config_path: str | None = typer.Option(None, "--config", "-c"),
    config_dir: str | None = typer.Option(None, "--config-dir"),
) -> None:
    """Run the QQ recovery probe independently (resolve + send summaries)."""
    cfg = _load(config_path, config_dir)
    configure_logging(cfg.app.log_level)
    database = Database(cfg.app.database_url)
    database.create_all()
    pipeline, buff, llm, qq = _build_pipeline(cfg, database)

    async def _run() -> None:
        try:
            result = await pipeline.run_once(dry_run=False)
            # run_once already calls probe_and_recover; echo a compact view.
            view = {
                "probe_runs": result.probe_runs,
                "probe_recovered": result.probe_recovered,
                "alerts_sent": result.alerts_sent,
            }
            typer.echo(json.dumps(view, indent=2))
        finally:
            await buff.aclose()
            await llm.aclose()
            await qq.aclose()

    asyncio.run(_run())


@app.command("test-notify")
def test_notify(
    config_path: str | None = typer.Option(None, "--config", "-c"),
    config_dir: str | None = typer.Option(None, "--config-dir"),
    message: str = typer.Option("BUFF Sentinel test notification", "--message"),
) -> None:
    """Send a test message via QQ Bot."""
    cfg = _load(config_path, config_dir)
    configure_logging(cfg.app.log_level)
    qq = QQBotClient(cfg.qq_bot)
    outcomes: list[dict[str, object]] = []

    async def _run() -> None:
        try:
            for openid in cfg.qq_bot.recipients:
                res = await qq.send_c2c_text(openid, message)
                outcomes.append(
                    {
                        "openid": openid[:6] + "…",
                        "ok": res.ok,
                        "status": res.status,
                        "detail": res.detail,
                    }
                )
        finally:
            await qq.aclose()

    asyncio.run(_run())
    typer.echo(json.dumps(outcomes, indent=2))
    if any(not row["ok"] for row in outcomes):
        raise typer.Exit(code=1)


@app.command()
def healthcheck(
    config_path: str | None = typer.Option(None, "--config", "-c"),
    config_dir: str | None = typer.Option(None, "--config-dir"),
    max_age_minutes: int = typer.Option(30, "--max-age-minutes"),
) -> None:
    """Confirm config parses, DB is reachable, and a recent snapshot exists."""
    cfg = _load(config_path, config_dir)
    configure_logging(cfg.app.log_level)
    database = Database(cfg.app.database_url)
    database.create_all()
    repo = Repository(database)

    status: dict[str, object] = {"config": "ok", "database": "ok"}
    latest_ok = False
    items: list[Any] = [*cfg.owned, *cfg.wishlist]
    for item in items:
        snap = repo.latest_snapshot(item.goods_id)
        if snap is None:
            continue
        age_min = (utcnow() - snap.captured_at).total_seconds() / 60.0
        if age_min <= max_age_minutes:
            latest_ok = True
            break
    status["recent_snapshot_within_min"] = max_age_minutes
    status["recent_snapshot_present"] = latest_ok
    typer.echo(json.dumps(status, indent=2))
    if not latest_ok:
        # Non-fatal on fresh installs.
        raise typer.Exit(code=1)


def main() -> None:  # pragma: no cover - entry indirection
    try:
        app()
    except typer.Exit:
        raise
    except Exception:
        LOG.exception("cli failed")
        sys.exit(1)


if __name__ == "__main__":  # pragma: no cover
    main()
