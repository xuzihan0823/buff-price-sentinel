# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m pip install --upgrade pip build && \
    python -m build --wheel --outdir /wheels

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN useradd --system --create-home --home-dir /home/sentinel --shell /usr/sbin/nologin sentinel && \
    mkdir -p /app /app/data /app/config && \
    chown -R sentinel:sentinel /app

WORKDIR /app

COPY --from=builder /wheels /wheels
RUN pip install /wheels/*.whl && rm -rf /wheels

USER sentinel
ENV BUFF_SENTINEL_CONFIG_DIR=/app/config

HEALTHCHECK --interval=5m --timeout=15s --start-period=10m --retries=3 \
    CMD buff-sentinel healthcheck --config-dir "$BUFF_SENTINEL_CONFIG_DIR" || exit 1

ENTRYPOINT ["buff-sentinel"]
CMD ["run"]
