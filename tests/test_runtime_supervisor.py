from utils.runtime_supervisor import expected_thread_names, missing_threads
from utils.process_roles import role_ownership


def test_vps_worker_thread_ownership():
    assert expected_thread_names(
        "publication", role_ownership("publication", True),
        telegram_configured=False,
    ) == frozenset({"daily-generation"})
    assert expected_thread_names(
        "settlement", role_ownership("settlement", True),
        telegram_configured=False,
    ) == frozenset({"results-checker"})
    assert expected_thread_names(
        "telegram", role_ownership("telegram", True),
        telegram_configured=True,
    ) == frozenset({"telegram-bot"})


def test_no_false_alarm_for_disabled_or_legacy_roles():
    for role in ("web", "worker", "scheduler", "all"):
        assert not expected_thread_names(
            role, role_ownership(role, True), telegram_configured=True,
        )
    assert not expected_thread_names(
        "publication", role_ownership("publication", False),
        telegram_configured=False,
    )
    assert not expected_thread_names(
        "telegram", role_ownership("telegram", True),
        telegram_configured=False,
    )


def test_missing_thread_detected_without_false_positive():
    expected = frozenset({"results-checker"})
    assert missing_threads(expected, {"other-thread"}) == expected
    assert not missing_threads(expected, {"other-thread", "results-checker"})
