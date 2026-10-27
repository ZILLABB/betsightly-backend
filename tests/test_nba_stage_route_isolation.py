"""NBA staging must never initialize football or growth tables."""
import os
import subprocess
import sys


def test_nba_private_mode_has_no_football_routes_or_startup_database_io():
    child = r"""
from sqlalchemy.engine import Engine
attempts = []
def blocked(self, *args, **kwargs):
    attempts.append("database_io")
    raise RuntimeError("No database IO allowed during isolated NBA startup")
Engine.connect = blocked

import main
paths = {route.path for route in main.app.routes}
assert "/api/growth/admin/nba-research" in paths
assert "/api/growth/internal/nba-research/github-oidc" in paths
assert "/api/growth/admin/login" in paths
assert not any(p.startswith("/api/leagues") for p in paths)
assert not any(p.startswith("/api/growth/manual") for p in paths)
assert not any(p.startswith("/api/growth/basketball-jackpot") for p in paths)
assert attempts == [], "Football/growth bootstrap attempted database I/O"
assert main.BACKGROUND_JOBS_ENABLED is False
"""
    env = dict(os.environ)
    env.update({
        "ENVIRONMENT": "staging",
        "NBA_PRIVATE_DATABASE_ONLY": "1",
        "NBA_USE_RESTORE_TARGET_AS_PRIMARY": "0",
        "ENABLE_BACKGROUND_JOBS": "false",
        "DATABASE_URL": "postgresql://research:masked@127.0.0.1:65432/offline",
    })
    done = subprocess.run([sys.executable, "-c", child], env=env,
                          capture_output=True, text=True, timeout=50)
    assert done.returncode == 0, done.stderr[-2200:]
