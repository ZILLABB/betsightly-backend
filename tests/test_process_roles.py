import pytest

from utils.process_roles import (
    resolve_process_role,
    role_ownership,
)


def test_worker_owns_all_background_jobs():
    assert role_ownership(
        "worker",
        True,
    ) == {
        "scheduler": True,
        "settlement": True,
        "telegram": True,
    }


def test_web_owns_no_background_jobs():
    assert role_ownership(
        "web",
        True,
    ) == {
        "scheduler": False,
        "settlement": False,
        "telegram": False,
    }


def test_background_disabled_overrides_worker():
    assert role_ownership(
        "worker",
        False,
    ) == {
        "scheduler": False,
        "settlement": False,
        "telegram": False,
    }


def test_compatibility_roles():
    assert role_ownership(
        "scheduler",
        True,
    ) == {
        "scheduler": True,
        "settlement": True,
        "telegram": False,
    }

    assert role_ownership(
        "telegram",
        True,
    ) == {
        "scheduler": False,
        "settlement": False,
        "telegram": True,
    }


def test_role_default_is_backward_compatible():
    assert resolve_process_role(
        True,
        "",
    ) == "all"

    assert resolve_process_role(
        False,
        "",
    ) == "web"


def test_invalid_role_fails_closed():
    with pytest.raises(
        RuntimeError
    ):
        resolve_process_role(
            True,
            "invalid",
        )

def test_vps_split_roles_are_independent():
    expected = {
        "web": (False, False, False),
        "publication": (True, False, False),
        "settlement": (False, True, False),
        "telegram": (False, False, True),
    }
    for role, (scheduler, settlement, telegram) in expected.items():
        resolved = resolve_process_role(True, role)
        assert resolved == role
        assert role_ownership(resolved, True) == {
            "scheduler": scheduler,
            "settlement": settlement,
            "telegram": telegram,
        }


def test_split_role_can_be_fully_disabled():
    for role in ("publication", "settlement", "telegram"):
        assert role_ownership(role, False) == {
            "scheduler": False,
            "settlement": False,
            "telegram": False,
        }
