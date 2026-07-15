"""Engine + session helpers with WAL for SQLite."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from buff_sentinel.storage.models import Base


class Database:
    """Wraps a SQLAlchemy engine and session factory."""

    def __init__(self, url: str) -> None:
        self.url = url
        self._ensure_directory(url)
        self.engine: Engine = create_engine(url, future=True, echo=False)
        if url.startswith("sqlite"):
            self._enable_sqlite_wal()
        self._session_factory = sessionmaker(
            bind=self.engine, expire_on_commit=False, future=True
        )

    @staticmethod
    def _ensure_directory(url: str) -> None:
        prefix = "sqlite:///"
        if not url.startswith(prefix):
            return
        raw = url[len(prefix):]
        if not raw or raw == ":memory:":
            return
        path = Path(raw)
        parent = path.parent
        if parent and not parent.exists():
            parent.mkdir(parents=True, exist_ok=True)

    def _enable_sqlite_wal(self) -> None:
        @event.listens_for(self.engine, "connect")
        def _set_pragmas(dbapi_conn: Any, _record: Any) -> None:
            cursor = dbapi_conn.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=WAL;")
                cursor.execute("PRAGMA synchronous=NORMAL;")
                cursor.execute("PRAGMA foreign_keys=ON;")
            finally:
                cursor.close()

    def create_all(self) -> None:
        Base.metadata.create_all(self.engine)

    def dispose(self) -> None:
        self.engine.dispose()

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
