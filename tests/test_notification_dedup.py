"""
Notifications go out once per publishing day, whatever restarts happen.

The bug: the guard was a module-level dict in main.py. It is empty in a new
process, so every deploy re-announced the day — one notification per push, and
two to four when a deploy cycled more than once. Nothing recorded that a
notification had been sent, so duplicates were neither preventable nor
visible afterwards.

These tests pin the two properties that fix it: the claim survives a process
restart, and each channel is claimed separately.
"""

import pytest
from sqlalchemy import text

from database import engine
import services.push_notification_service as P


DAY = "1999-03-03"


@pytest.fixture(autouse=True)
def clean():
    def _clear():
        try:
            with engine.begin() as conn:
                P.NotificationDelivery.__table__.create(conn, checkfirst=True)
                conn.execute(
                    text("DELETE FROM notification_deliveries "
                         "WHERE publish_date = :d"), {"d": DAY})
        except Exception:
            pass
    _clear()
    yield
    _clear()


@pytest.fixture
def no_network(monkeypatch):
    """Record what would have been sent without sending it."""
    sent = {"push": 0, "dm": 0}
    monkeypatch.setattr(P, "send_push_to_all",
                        lambda **k: sent.__setitem__("push", sent["push"] + 1))
    monkeypatch.setattr(P, "send_telegram_dm_to_all",
                        lambda m: sent.__setitem__("dm", sent["dm"] + 1))
    return sent


# ── Claiming ───────────────────────────────────────────────

def test_first_claim_wins_and_the_second_loses():
    assert P.claim_delivery(DAY, "web_push", P.KIND_PREDICTIONS_READY)
    assert not P.claim_delivery(DAY, "web_push", P.KIND_PREDICTIONS_READY)


def test_the_claim_lives_in_the_database_not_in_memory():
    """The whole point. An in-memory guard could not do this.

    A restarted process keeps no module state, so the only thing that can
    refuse the second send is a row somewhere durable. Asserting the row
    exists is the property — reloading the module would only prove that
    SQLAlchemy dislikes being re-imported.
    """
    assert P.claim_delivery(DAY, "web_push", P.KIND_PREDICTIONS_READY)
    with engine.begin() as conn:
        n = conn.execute(text(
            "SELECT COUNT(*) FROM notification_deliveries"
            " WHERE publish_date = :d AND channel = 'web_push'"),
            {"d": DAY}).scalar()
    assert n == 1, "the claim must be durable, not a process-local flag"
    assert not P.claim_delivery(DAY, "web_push", P.KIND_PREDICTIONS_READY)


def test_no_module_level_flag_guards_the_alert():
    """main.py used to hold `_ALERTED`, which is what reset on every deploy."""
    import main
    assert not hasattr(main, "_ALERTED"), \
        "an in-process guard is what caused the duplicates"


def test_channels_are_claimed_independently():
    """A Telegram outage must not cost the web push, or resend it."""
    assert P.claim_delivery(DAY, "web_push", P.KIND_PREDICTIONS_READY)
    assert P.claim_delivery(DAY, "telegram_dm", P.KIND_PREDICTIONS_READY)


def test_different_days_are_separate():
    assert P.claim_delivery(DAY, "web_push", P.KIND_PREDICTIONS_READY)
    assert P.claim_delivery("1999-03-04", "web_push", P.KIND_PREDICTIONS_READY)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM notification_deliveries "
                          "WHERE publish_date = '1999-03-04'"))


def test_different_kinds_are_separate():
    assert P.claim_delivery(DAY, "web_push", P.KIND_PREDICTIONS_READY)
    assert P.claim_delivery(DAY, "web_push", P.KIND_RESULTS_UPDATED)


# ── The alert itself ───────────────────────────────────────

def test_the_alert_is_sent_once_however_many_times_it_is_called(no_network):
    for _ in range(5):
        P.notify_predictions_ready(DAY, 23, {"banker": True, "2_odds": True})
    assert no_network == {"push": 1, "dm": 1}


def test_an_empty_card_is_never_announced(no_network):
    """A notification that cannot state a real number is worse than none."""
    P.notify_predictions_ready(DAY, 0, {})
    assert no_network == {"push": 0, "dm": 0}
    # and it must not have burned the claim either
    assert P.claim_delivery(DAY, "web_push", P.KIND_PREDICTIONS_READY)


def test_results_alerts_are_guarded_too(no_network):
    """Settlement runs hourly, so an unguarded call would announce every hour."""
    for _ in range(4):
        P.notify_results_updated(DAY, 8, 3)
    assert no_network["push"] == 1


# ── Failure behaviour ──────────────────────────────────────

def test_an_unreachable_database_does_not_become_a_reason_to_spam(monkeypatch):
    """Failing closed is the right direction: miss one rather than repeat one."""
    def _boom():
        raise RuntimeError("db down")
    monkeypatch.setattr(P, "SessionLocal", _boom)
    assert not P.claim_delivery(DAY, "web_push", P.KIND_PREDICTIONS_READY)


def test_delivery_is_recorded_for_audit(no_network):
    P.notify_predictions_ready(DAY, 12, {"banker": True})
    rows = [r for r in P.delivery_log(200) if r["publish_date"] == DAY]
    assert {r["channel"] for r in rows} == {"web_push", "telegram_dm"}
    assert all(r["status"] == "sent" for r in rows)
