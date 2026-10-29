"""Fail closed when the explicitly selected VPS database is unavailable.

Inactive on legacy Render unless BETSIGHTLY_VPS_REQUIRE_DB=true.
Never print the supplied URL or database credentials in exception text.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from sqlalchemy import text


def validate_vps_db_url(url: str):
    try:
        value = urlsplit(url)
        params = parse_qs(value.query)
        if (
            value.scheme not in ("postgresql", "postgresql+psycopg2", "postgres")
            or not value.username or not value.password or not value.hostname
            or not value.path.lstrip("/")
            or value.hostname in ("127.0.0.1", "localhost")
            or value.username == "example"
            or value.password == "change-me"
            or params.get("sslmode") not in (
                ["require"], ["verify-ca"], ["verify-full"]
            )
        ):
            raise ValueError("invalid URL")
        return True
    except (TypeError, ValueError):
        raise RuntimeError(
            "VPS_DATABASE_NOT_CONFIGURED: use a private, TLS-required PostgreSQL URL"
        ) from None


def verify_vps_database(url, engine):
    validate_vps_db_url(url)
    try:
        with engine.connect() as conn:
            if conn.execute(text("SELECT 1")).scalar_one() != 1:
                raise RuntimeError("unhealthy query result")
    except Exception:
        raise RuntimeError("VPS_DATABASE_UNREACHABLE") from None
    return True
