"""Database engine, session management, and schema initialization.

Uses SQLAlchemy 2.0 ORM over a local SQLite file (``data/scanner.sqlite3``).
SQLite is deliberately chosen for a zero-dependency local MVP.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.config import settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


# `check_same_thread=False` is required because the scheduler thread and the
# request threads both touch the DB. Each unit of work uses its own session.
engine = create_engine(
    settings.database_url,
    echo=False,
    future=True,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    """Create all tables if they do not yet exist."""
    # Import models so they are registered on `Base.metadata` before create_all.
    from backend import models  # noqa: F401  (side-effect import)

    Base.metadata.create_all(bind=engine)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Provide a transactional scope around a series of operations."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency that yields a request-scoped session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
