import pytest
from sqlalchemy import create_engine

from utils.vps_startup import validate_vps_db_url, verify_vps_database


@pytest.mark.parametrize("url", [
    "", "sqlite:///test.db",
    "postgresql://example:change-me@db.internal.example/betsightly?sslmode=require",
    "postgresql://svc:pw@127.0.0.1/betsightly?sslmode=require",
    "postgresql://svc:pw@db.internal.example/betsightly?sslmode=disable",
    "postgresql://svc:pw@db.internal.example/betsightly",
    "postgresql://svc:pw@db.internal.example/betsightly?sslmode=prefer",
])
def test_refuses_empty_placeholder_local_and_insecure_database_urls(url):
    with pytest.raises(RuntimeError, match="VPS_DATABASE_NOT_CONFIGURED"):
        validate_vps_db_url(url)


def test_valid_tls_database_url_is_accepted():
    url = "postgresql://svc:pw@db.internal.example/betsightly?sslmode=require"
    assert validate_vps_db_url(url)


def test_successful_read_only_probe_uses_select_one():
    e = create_engine("sqlite:///:memory:")
    try:
        assert verify_vps_database(
            "postgresql://svc:pw@db.internal.example/betsightly?sslmode=require", e
        )
    finally:
        e.dispose()


class _BrokenEngine:
    def connect(self):
        raise OSError("contains a secret that must never appear")


def test_connection_failure_is_sanitized():
    with pytest.raises(RuntimeError, match="^VPS_DATABASE_UNREACHABLE$") as err:
        verify_vps_database(
            "postgresql://svc:secret@db.internal.example/db?sslmode=require",
            _BrokenEngine(),
        )
    assert "secret" not in str(err.value)
