"""
Shared pytest fixtures for the BetSightly test suite.
"""

import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Use SQLite in-memory for tests — no PostgreSQL required
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
# Test imports must never inherit a production shell's background-job flags.
# A prepared-board prewarm performs real provider I/O, while settlement and
# publishing mutate state, so make the suite's process ownership explicit.
os.environ["ENVIRONMENT"] = "test"
os.environ["ENABLE_BACKGROUND_JOBS"] = "false"
os.environ.setdefault("API_KEY", "")  # disable auth in tests

from database import Base, get_db
from main import app


@pytest.fixture(scope="session")
def test_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(test_engine):
    TestingSession = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)
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
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
