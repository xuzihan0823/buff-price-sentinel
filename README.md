# BUFF Price Sentinel

Open-source Python service that monitors configured BUFF CS2 goods every 10
minutes, retains seven days of local price history, evaluates owned/wishlist
rules, requests structured analysis from an OpenAI-compatible LLM, and pushes
alerts through the official QQ Bot C2C API.

## Highlights

- Strict split-YAML config for 10-100 goods, divided into `owned` and
  `wishlist`.
- Async BUFF first-page sell/buy client with pacing, retries, partial-data
  handling, and no zero-price writes.
- SQLite WAL storage with seven-day rolling snapshots and longer retention for
  alerts, LLM analyses, and QQ incident history.
- Rolling 1h/6h/24h/3d/7d trend summaries and coverage ratio.
- LLM analysis via OpenAI-compatible `/chat/completions` with strict JSON
  schema validation and safe fail-open fallback to rule-only alerts.
- Official QQ Bot C2C delivery with incident tracking and one recovery summary
  after the platform is healthy again.
- Docker Compose deployment without published ports; production images use a
  fixed GHCR digest.

## Local setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'

mkdir -p config
cp config/app.example.yaml config/app.yaml
cp config/items.example.yaml config/items.yaml
cp config/llm.example.yaml config/llm.yaml
cp config/notifiers.example.yaml config/notifiers.yaml
```

Edit the copied files and supply secrets through the environment:

```bash
export LLM_API_KEY=...
export QQ_APP_ID=...
export QQ_CLIENT_SECRET=...
export QQ_RECIPIENT_OPENID=...
# Optional:
export BUFF_SESSION_COOKIE=...

buff-sentinel validate-config --config-dir config
buff-sentinel once --config-dir config --dry-run
buff-sentinel run --config-dir config
```

The production constraint is 10-100 unique goods across `owned` and
`wishlist`. Local config files, `.env` files, and SQLite data are ignored by
Git. Do not commit them.

## Configuration

The four tracked examples are:

| File | Purpose |
| --- | --- |
| `config/app.example.yaml` | Timezone, SQLite URL, collection cadence, BUFF request behavior, alert cooldowns |
| `config/items.example.yaml` | Owned and wishlist goods plus thresholds |
| `config/llm.example.yaml` | OpenAI-compatible base URL, model, retry and fail-open behavior |
| `config/notifiers.example.yaml` | QQ Bot endpoints, credentials, recipients, retry behavior |

Environment references use `${NAME}` or `${NAME:-default}`. The loader rejects
missing required variables and invalid configurations.

For containers, set `database_url` to
`sqlite:////app/data/buff-sentinel.db`, as the application data directory is a
named Docker volume. The tracked app example already uses this default and can
be overridden with `BUFF_SENTINEL_DATABASE_URL` for local development.

## CLI

```text
buff-sentinel run              # Start the daemon (10-minute cadence)
buff-sentinel once             # Run one collection round
buff-sentinel validate-config  # Load and summarize configuration
buff-sentinel test-notify      # Send a QQ Bot test message
buff-sentinel healthcheck      # Validate config, database, and recent snapshot
```

All commands accept `--config-dir <directory>`. `once --dry-run` fetches BUFF
quotes, writes snapshots, and evaluates rules, but skips LLM calls, QQ sends,
and alert-dedup writes.

## Docker and production deployment

Production uses a public GHCR image pinned by digest. The server never builds
source code and exposes no ports.

1. Obtain the digest from the successful GitHub Actions workflow summary:

   ```text
   ghcr.io/xuzihan0823/buff-price-sentinel@sha256:<digest>
   ```

2. On the server, create the runtime files outside the Git checkout:

   ```text
   /root/buff-price-sentinel/
     docker-compose.yml
     secrets.env
     config/
       app.yaml
       items.yaml
       llm.yaml
       notifiers.yaml
     backups/
   ```

3. Put the digest and application secrets in `secrets.env` with mode `0600`:

   ```dotenv
   IMAGE_REF=ghcr.io/xuzihan0823/buff-price-sentinel@sha256:<digest>
   LLM_API_KEY=...
   QQ_APP_ID=...
   QQ_CLIENT_SECRET=...
   QQ_RECIPIENT_OPENID=...
   BUFF_SESSION_COOKIE=
   TZ=Asia/Shanghai
   ```

4. Validate and start the service:

   ```bash
   docker compose --env-file secrets.env config
   docker compose --env-file secrets.env pull
   docker compose --env-file secrets.env up -d --remove-orphans
   docker compose --env-file secrets.env ps
   ```

The healthcheck needs a recent BUFF snapshot, so a fresh installation can show
`starting` or `unhealthy` until the first successful collection. Verify it after
`once --dry-run` or the first scheduled collection:

```bash
docker compose --env-file secrets.env exec -T buff-sentinel \
  buff-sentinel healthcheck --config-dir /app/config
docker compose --env-file secrets.env logs --since 20m buff-sentinel
```

## Backup and rollback

Before replacing an existing server deployment, create a timestamped archive of
`/root/buff-price-sentinel` and a consistent SQLite backup, verify both, then
remove only the prior backup for this project. Keep deployment metadata in a
root-owned `RELEASE` file containing the commit, image digest, deployment time,
and backup filename.

To roll back a failed release, set `IMAGE_REF` to the previous successful digest
from `RELEASE`, run `docker compose --env-file secrets.env pull`, then run
`docker compose --env-file secrets.env up -d --remove-orphans`. Do not use
`latest` as a rollback target.

## Development

```bash
ruff check src tests
mypy src
pytest
docker build --tag buff-price-sentinel:local .
```

GitHub Actions runs the same quality checks before publishing main-branch images
to GHCR. It publishes short SHA, full SHA, branch, and convenience `latest`
tags; production deployment must use the immutable digest reported by the
workflow.

## Design summary

See `.trellis/tasks/07-14-buff-price-sentinel/design.md` for the layered
boundaries: `config`, `buff`, `storage`, `analytics`, `llm`, `notifier`,
`service`, and `cli`.

## License

MIT.
