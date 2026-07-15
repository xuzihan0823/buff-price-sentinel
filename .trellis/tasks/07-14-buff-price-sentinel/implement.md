# Implementation Checklist

1. Add Python package metadata, config examples, ignore files, and progress log.
2. Implement strict config schemas/loaders and SQLite models/repositories.
3. Implement BUFF async client/parser/limiter and collection pipeline.
4. Implement trend windows, owned/wishlist rules, deduplication, and periodic review.
5. Implement OpenAI-compatible structured LLM client and fallback behavior.
6. Implement official QQ Bot C2C token/message client, incident tracking, and recovery summary.
7. Implement scheduler and CLI commands.
8. Add unit/component tests and representative HTTP fixtures.
9. Add Docker/Compose, CI/GHCR workflows, README, and Trellis specs.
10. Run ruff, mypy, pytest, Docker build, local real-data smoke test, and healthcheck.
11. Inspect GitHub/remote credentials and server state; only then publish/deploy with backup and rollback steps.
