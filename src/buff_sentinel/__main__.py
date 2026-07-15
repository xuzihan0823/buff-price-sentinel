"""Entrypoint so `python -m buff_sentinel ...` works."""

from __future__ import annotations

from buff_sentinel.cli import app

if __name__ == "__main__":
    app()
