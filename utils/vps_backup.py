"""Safe PostgreSQL backup argument preparation; never put DB secrets in argv."""

from __future__ import annotations

import os
from urllib.parse import parse_qs, unquote, urlsplit

ALLOWED_SSL = frozenset({"require", "verify-ca", "verify-full"})


def pg_environment(database_url: str, *, inherited=None):
    url = urlsplit(database_url)
    if url.scheme not in ("postgresql", "postgresql+psycopg2"):
        raise ValueError("PostgreSQL URL required")
    database = unquote(url.path.lstrip("/"))
    if not database or "/" in database or not url.hostname or not url.username:
        raise ValueError("host, user and database must be provided")
    params = parse_qs(url.query, strict_parsing=True)
    # Fail closed on exotic URL options rather than silently weakening TLS.
    if set(params) - {"sslmode"}:
        raise ValueError("unsupported PostgreSQL URL query parameters")
    mode = params.get("sslmode", ["require"])[0]
    if mode not in ALLOWED_SSL:
        raise ValueError("TLS requires sslmode=require, verify-ca or verify-full")

    env = dict(os.environ if inherited is None else inherited)
    for key in tuple(env):
        if key.startswith("PG") and key in {
            "PGHOST", "PGPORT", "PGUSER", "PGPASSWORD", "PGDATABASE",
            "PGSSLMODE", "PGSERVICE", "PGPASSFILE", "PGOPTIONS",
            "PGHOSTADDR", "PGCONNECT_TIMEOUT",
        }:
            env.pop(key)
    env.update({
        "PGHOST": url.hostname,
        "PGPORT": str(url.port or 5432),
        "PGUSER": unquote(url.username),
        "PGPASSWORD": unquote(url.password or ""),
        "PGDATABASE": database,
        "PGSSLMODE": mode,
        "PGCONNECT_TIMEOUT": "10",
    })
    return env, database
