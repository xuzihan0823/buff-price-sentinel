# Technical Design

## Boundaries
- `config`: Pydantic schemas and YAML/env interpolation.
- `buff`: HTTP transport and response parsing only.
- `storage`: SQLAlchemy models and repositories.
- `analytics`: deterministic trend and trigger logic.
- `llm`: OpenAI-compatible transport plus strict output schema.
- `notifier`: official QQ token/message client, incident tracking, formatting.
- `service`: collection/evaluation orchestration and scheduler.
- `cli`: process entry points.

## Data Flow
1. Scheduler launches one collection round every 10 minutes.
2. BUFF client fetches first-page sell/buy orders per goods ID under a shared limiter.
3. Pipeline persists successful/partial snapshots; unknown prices remain null.
4. Trend service loads the rolling seven-day series and computes summary windows.
5. Rule engine emits candidates. Repository atomically inserts dedup keys and enforces cooldown.
6. LLM analyzes the compact numeric summary. Invalid/unavailable analysis degrades to a rule-only alert.
7. QQ notifier attempts C2C delivery and records success/failure. Recovery probe sends one outage summary.

## Persistence
SQLite WAL with `price_snapshots`, `alert_events`, `llm_analyses`, and `service_incidents`. Store UTC timestamps; display in configured timezone. Delete snapshots older than seven days and operational history older than its configured retention.

## Reliability
- Limit BUFF concurrency and pace requests with jitter; back off on 429/5xx.
- Never coerce missing/failed prices to zero.
- `max_instances=1` prevents overlapping collection rounds.
- Strict JSON and Pydantic validation guard model output.
- A QQ API call is successful only after a successful platform response; QQ outages are recorded and summarized after recovery.

## Security
Secrets enter through environment variables referenced by local YAML. Logs redact authorization headers and credentials. The container runs as a non-root user. No BUFF login cookie is required in the default path.
