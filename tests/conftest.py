"""Shared pytest fixtures: an isolated in-memory database session."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.db import Base
from backend import models  # noqa: F401  (register tables on Base.metadata)


@pytest.fixture()
def session() -> Session:
    """A fresh in-memory SQLite session per test (no shared state)."""
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()
