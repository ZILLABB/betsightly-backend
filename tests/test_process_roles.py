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
