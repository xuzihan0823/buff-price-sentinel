# BUFF Price Sentinel — Progress Log

## 2026-07-14

Initial MVP implementation completed.

### Delivered

- Project scaffolding: `pyproject.toml` (Python 3.12, src layout), `.gitignore`,
  `.dockerignore`, and split examples under `config/*.example.yaml`.
- `buff_sentinel.config` — strict Pydantic v2 schemas with `${ENV[:-default]}`
  interpolation and validation (owned/wishlist entries, ranges, duplicate
  goods_id guard, ≤100 items).
- `buff_sentinel.storage` — SQLAlchemy 2 models (`price_snapshots`,
  `alert_events`, `llm_analyses`, `service_incidents`), SQLite WAL/pragma
  hooks, repository with dedup + cooldown, snapshot pruning, and incident
  lifecycle.
- `buff_sentinel.buff` — async httpx client with limiter, jittered pacing,
  429/5xx exponential backoff, robust null / zero handling on sell + buy
  first pages.
- `buff_sentinel.analytics` — rolling 1h/6h/24h/3d/7d windows, coverage
  ratio, and rule engine for owned P/L, wishlist floor, wishlist 24h drop,
  and periodic wishlist review (default 3 days).
- `buff_sentinel.llm` — OpenAI-compatible `/chat/completions` client with
  strict JSON output schema (`verdict/confidence/risk/reasoning/action`),
  retries, and safe fail-open fallback that flags rule-only alerts.
- `buff_sentinel.notifier` — official QQ Bot C2C client
  (`https://bots.qq.com/app/getAppAccessToken` +
  `https://api.sgroup.qq.com/v2/users/{openid}/messages`), token cache,
  retries, alert/recovery formatters, and outage-summary support.
- `buff_sentinel.service` — collection pipeline (fetch → persist → evaluate →
  analyze → notify → recovery summary) and APScheduler runner with
  `max_instances=1`, `coalesce=True`, and signal handling.
- `buff_sentinel.cli` — Typer app: `run`, `once`, `validate-config`,
  `test-notify`, `healthcheck` (non-zero exit when a recent snapshot is
  missing).
- Tests (40 total, all passing): config validation, storage/dedup/incident,
  BUFF client (respx), analytics + rules (incl. 3-day review), LLM (schema
  reject + fail-open), notifier (token cache, formatters), pipeline
  (QQ outage → recovery summary), CLI smoke.
- Docker: multi-stage build, non-root `sentinel` user, healthcheck via
  `buff-sentinel healthcheck`, `docker-compose.yml` with env-driven secrets
  and persistent data volume.
- CI: `.github/workflows/ci.yml` runs ruff, mypy, pytest, and (on `main`)
  builds + pushes immutable SHA-tagged images to GHCR and reports the digest.
- Docs: `README.md`, split config examples, this `PROGRESS.md`.

### Verification

- `ruff check src tests` — clean.
- `mypy src` — clean (24 files).
- `pytest` — 40 passed.
- `docker build --pull --tag buff-price-sentinel:local .` — passed on
  2026-07-15; image runs as `sentinel` and uses split-config healthcheck.
- Compose rendering — passed with a fixed digest reference, no published ports,
  split config mount, and stable named SQLite volume.
- Real BUFF/LLM/QQ smoke test: pending live production configuration; credentials
  must never be committed.

### Follow-ups

- Collect the real 10-100 goods configuration and LLM/QQ credentials, then run
  the authorized BUFF dry-run, LLM analysis, QQ delivery, persistence, and
  healthcheck smoke tests.
- Publish the public GitHub repository and GHCR image, then deploy the reported
  immutable digest to `43.160.200.14:/root/buff-price-sentinel`.
- Populate `.trellis/spec/backend/*.md` files with concrete conventions
  now that the layout exists.
- Consider promoting the healthcheck to also verify pipeline heartbeat
  (last successful collection round timestamp) once operational data is
  available.
