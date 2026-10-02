"""Pure runtime process ownership rules."""

from __future__ import annotations


VALID_PROCESS_ROLES = frozenset({
    "web",
    "worker",
    "scheduler",
    "telegram",
    "all",
})


def resolve_process_role(
    background_jobs: bool,
    configured_role: str | None,
) -> str:
    role = str(configured_role or "").strip().lower()

    if not role:
        role = "all" if background_jobs else "web"

    if role not in VALID_PROCESS_ROLES:
        raise RuntimeError(
            "Invalid BETSIGHTLY_PROCESS_ROLE: "
            f"{role}"
        )

    return role


def role_ownership(
    role: str,
    background_jobs: bool,
) -> dict[str, bool]:
    role = str(role or "").strip().lower()

    if role not in VALID_PROCESS_ROLES:
        raise RuntimeError(
            "Invalid BETSIGHTLY_PROCESS_ROLE: "
            f"{role}"
        )

    if not background_jobs:
        return {
            "scheduler": False,
            "settlement": False,
            "telegram": False,
        }

    if role in {"worker", "all"}:
        return {
            "scheduler": True,
            "settlement": True,
            "telegram": True,
        }

    if role == "scheduler":
        return {
            "scheduler": True,
            "settlement": True,
            "telegram": False,
        }

    if role == "telegram":
        return {
            "scheduler": False,
            "settlement": False,
            "telegram": True,
        }

    return {
        "scheduler": False,
        "settlement": False,
        "telegram": False,
    }
