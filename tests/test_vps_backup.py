import pytest

from utils.vps_backup import pg_environment


def test_password_is_not_in_pg_command_arguments():
    url = "postgresql://svc:pw%3Asecret@example.org:6543/betsightly?sslmode=verify-full"
    env, name = pg_environment(url, inherited={"PATH": "/usr/bin", "PGSERVICE": "untrusted"})
    assert name == "betsightly"
    assert env["PGPASSWORD"] == "pw:secret"
    assert env["PGSSLMODE"] == "verify-full"
    assert env["PGPORT"] == "6543"
    assert "PGSERVICE" not in env


@pytest.mark.parametrize("url", [
    "sqlite:///football.db",
    "postgresql://user:pw@example.org/",
    "postgresql://user:pw@localhost/test?sslmode=disable",
    "postgresql://user:pw@localhost/test?options=-c%20statement_timeout%3D0",
    "postgresql://user:pw@/test",
])
def test_bad_database_urls_fail_closed(url):
    with pytest.raises(ValueError):
        pg_environment(url, inherited={})


def test_tls_is_required_by_default():
    env, database = pg_environment("postgresql://app:pwd@localhost/betsightly",
                                   inherited={})
    assert database == "betsightly"
    assert env["PGSSLMODE"] == "require"
