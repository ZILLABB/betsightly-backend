"""Verify the *rendered* VPS Compose contract (stdlib only).

Run after 'docker compose ... config --format json > /tmp/vps-compose.json'.
No network or credentials are read by this script.
"""

import argparse
import json
from pathlib import Path

from utils.process_roles import role_ownership

ROLES = {
    "api": "web",
    "publication": "publication",
    "settlement": "settlement",
    "telegram": "telegram",
}


def verify(compose):
    services = compose.get("services") or {}
    for name in ("publication", "settlement"):
        assert "writers" in (services.get(name, {}).get("profiles") or []), (
            f"{name} must be explicitly opt-in via the writers profile"
        )
    for name, role in ROLES.items():
        assert name in services, f"missing {name}"
        service = services[name]
        env = service.get("environment") or {}
        assert env.get("BETSIGHTLY_PROCESS_ROLE") == role, name
        enabled = str(env.get("ENABLE_BACKGROUND_JOBS", "")).lower()
        assert enabled == ("false" if name == "api" else "true"), name
        assert env.get("ENVIRONMENT") == "production", name
        assert service.get("restart") == "unless-stopped", name
        assert env.get("DATABASE_URL", "").startswith(
            ("postgresql://", "postgresql+psycopg2://")
        ), f"{name}: use PostgreSQL, not SQLite"
        if name != "api":
            assert service.get("command") == ["python", "-m", "run_background"], name

    for task in ("scheduler", "settlement", "telegram"):
        owners = [n for n, r in ROLES.items()
                  if role_ownership(r, n != "api")[task]]
        assert owners == [{
            "scheduler": "publication",
            "settlement": "settlement",
            "telegram": "telegram",
        }[task]], f"unexpected {task} owners: {owners}"

    api = services["api"]
    assert api.get("healthcheck"), "missing API health check"
    ports = api.get("ports") or []
    assert ports and all(p.get("host_ip") == "127.0.0.1" for p in ports), (
        "API must remain loopback-bound until TLS proxy is installed"
    )
    assert "telegram" in (services["telegram"].get("profiles") or []), (
        "telegram must be explicitly enabled when credentials are configured"
    )
    for name in ("publication", "settlement", "telegram"):
        assert services[name]["environment"].get("BETSIGHTLY_VPS_WRITER_ACTIVATION") == "disabled", (
            "example environment must not pre-authorize writers"
        )
    print("VPS_COMPOSE_CONTRACT_OK: opt-in isolated API, publication, settlement, Telegram")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("rendered_compose", type=Path)
    args = parser.parse_args()
    verify(json.loads(args.rendered_compose.read_text(encoding="utf-8")))


if __name__ == "__main__":
    main()
