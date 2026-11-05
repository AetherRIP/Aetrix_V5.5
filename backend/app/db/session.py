"""Engine and session management.

The engine is created lazily so importing the application never opens a
connection.  The API and the worker share the same session factory; neither
holds a transaction open across a request or a job step.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from ..core.config import Settings, get_settings

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def _engine_kwargs(settings: Settings) -> dict[str, Any]:
    return {
        "pool_pre_ping": settings.database.pool_pre_ping,
        "pool_size": settings.database.pool_size,
        "max_overflow": settings.database.max_overflow,
        "pool_recycle": settings.database.pool_recycle_seconds,
        "connect_args": {"connect_timeout": 15},
        "future": True,
    }


def get_engine(settings: Settings | None = None) -> Engine:
    global _engine
    if _engine is None:
        resolved = settings or get_settings()
        _engine = create_engine(resolved.database.dsn(), **_engine_kwargs(resolved))
    return _engine


def get_session_factory(settings: Settings | None = None) -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_engine(settings),
            expire_on_commit=False,
            autoflush=False,
            class_=Session,
        )
    return _session_factory


@contextmanager
def session_scope(settings: Settings | None = None) -> Iterator[Session]:
    session = get_session_factory(settings)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db_session() -> Iterator[Session]:
    """FastAPI dependency.  Services own their commits; this is the safety net."""
    with session_scope() as session:
        yield session


def reset_engine() -> None:
    """Test helper: dispose and forget the process-wide engine."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
