# Build BUFF Price Sentinel

## Goal

Create an open-source Python service that monitors configured BUFF CS2 goods every 10 minutes, retains seven days of local history, evaluates owned/wishlist rules, requests structured analysis from a configurable new-api-compatible LLM, and sends alerts through the official QQ Bot C2C API.

## Requirements

- Configure 10-100 goods in strict YAML, split into owned and wishlist entries.
- Owned entries trigger on configurable profit/loss percentages measured from `sell_min_price` versus purchase price.
- Wishlist entries trigger on target floor price or configurable 24-hour relative change; each is analyzed at least once every three days.
- Collect first-page sell and buy orders by BUFF `goods_id`, with rate limiting, jitter, retries, partial-data handling, and no zero-price writes on failures.
- Store rolling seven-day snapshots in SQLite; retain alert/analysis/incident history longer for review.
- Compute 1h/6h/24h/3d/7d trend summaries and coverage.
- Call an OpenAI-compatible `/chat/completions` endpoint configured by base URL, key, and model ID; strictly validate JSON output.
- Attempt official QQ Bot private push. Record failures honestly; after QQ recovers, send a compact outage/missed-alert summary because no backup channel is configured.
- Provide CLI commands for daemon run, one collection, config validation, notification test, and healthcheck.
- Provide tests, Docker/Compose, GitHub Actions, GHCR release flow, README, and operational progress log.
- Initialize and preserve Trellis support for Claude and Codex.

## Acceptance Criteria

- [ ] Ruff, mypy, pytest, and Docker build pass.
- [ ] A real configured BUFF goods ID can produce a valid snapshot locally.
- [ ] Rules, three-day review, deduplication, LLM failure fallback, and QQ recovery summary are covered by tests.
- [ ] No secret or real user config is committed.
- [ ] The service can run non-root in Docker with persistent config/data mounts and a meaningful healthcheck.
