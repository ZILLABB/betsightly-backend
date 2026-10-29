"""Fail-closed safety contract for the Git-backed Coolify Compose file."""

import json
import sys
from pathlib import Path

ROLES = {"api": "web", "publication": "publication",
         "settlement": "settlement", "telegram": "telegram"}


def verify_compose(obj):
    services = obj["services"]
    for name, role in ROLES.items():
        svc = services[name]
        if svc.get("ports"):
            raise ValueError(f"{name}: host ports are forbidden in Coolify")
        env = svc["environment"]
        if env.get("BETSIGHTLY_PROCESS_ROLE") != role:
            raise ValueError(f"{name}: incorrect process role")
        if env.get("BETSIGHTLY_VPS_REQUIRE_DB") != "true":
            raise ValueError(f"{name}: DB fail-closed guard disabled")
        if str(env.get("ENABLE_BACKGROUND_JOBS")).lower() != (
            "false" if name == "api" else "true"
        ):
            raise ValueError(f"{name}: wrong job ownership")
        if env.get("BETSIGHTLY_VPS_WRITER_ACTIVATION") != "disabled":
            raise ValueError(f"{name}: writers must be disabled in CI")
        if not env.get("DATABASE_URL", "").startswith("postgresql"):
            raise ValueError(f"{name}: invalid PostgreSQL configuration")
    for name, profile in (("publication", "writers"), ("settlement", "writers"),
                          ("telegram", "telegram")):
        if profile not in services[name].get("profiles", []):
            raise ValueError(f"{name}: writer must be opt-in")
    if not services["api"].get("healthcheck"):
        raise ValueError("API health check missing")
    print("COOLIFY_GIT_COMPOSE_CONTRACT_OK")


if __name__ == "__main__":
    verify_compose(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
