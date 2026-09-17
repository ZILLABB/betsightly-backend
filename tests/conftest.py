"""Shared pytest fixtures with isolated runtime state and caches."""
import os
import shutil
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


_ROOT = Path(tempfile.mkdtemp(prefix="betsightly-pytest-cache-"))
os.environ.setdefault("BETSIGHTLY_CACHE_ROOT", str(_ROOT))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ["ENVIRONMENT"] = "test"
os.environ["ENABLE_BACKGROUND_JOBS"] = "false"
os.environ.setdefault("API_KEY", "")

# Preserve seeded cache semantics while ensuring all writes land in temp.
_REPO = Path(__file__).resolve().parents[1]
for source in [*(_REPO / "leagues" / "data").glob("*.json"),
               *(_REPO / "cache").glob("*.json")]:
    shutil.copy2(source, _ROOT / source.name)

from database import Base, get_db
from main import app


@pytest.fixture(scope="session")
def test_engine():
    test_db = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=test_db)
    yield test_db
    test_db.dispose()


@pytest.fixture
def db_session(test_engine):
    TestingSession = sessionmaker(
        bind=test_engine, autocommit=False, autoflush=False,
    )
    session = TestingSession()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
