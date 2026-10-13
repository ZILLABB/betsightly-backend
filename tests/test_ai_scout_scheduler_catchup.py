"""Scheduler catch-up after an API key is configured post-publication."""
from leagues import ai_scout


def test_scout_scheduler_skips_when_disabled(monkeypatch):
    monkeypatch.delenv("AI_SCOUT_ENABLED", raising=False)
    calls = []
    assert ai_scout.scheduler_shadow_tick(
        "2026-10-13", None,
        runner=lambda **kw: calls.append(kw),
    ) is None
    assert not calls


def test_scout_scheduler_runs_after_daily_publisher_already_completed(monkeypatch):
    monkeypatch.setenv("AI_SCOUT_ENABLED", "true")
    dates = []
    def run(*, day):
        dates.append(day)
        return {"status": "SHADOW_EVIDENCE_ONLY"}
    today = ai_scout.scheduler_shadow_tick(
        "2026-10-13", None, runner=run,
    )
    assert today == "2026-10-13"
    assert ai_scout.scheduler_shadow_tick(
        "2026-10-13", today, runner=run,
    ) == "2026-10-13"
    assert dates == ["2026-10-13"]


def test_cold_board_and_missing_key_are_retryable_without_cost(monkeypatch):
    monkeypatch.setenv("AI_SCOUT_ENABLED", "true")
    for status in ("NO_API_KEY", "BOARD_UNAVAILABLE"):
        assert ai_scout.scheduler_shadow_tick(
            "2026-10-13", None,
            runner=lambda **kw: {"status": status},
        ) is None


def test_paid_api_error_does_not_loop_every_fifteen_minutes(monkeypatch):
    monkeypatch.setenv("AI_SCOUT_ENABLED", "true")
    calls = []
    def failing(*, day):
        calls.append(day)
        raise RuntimeError("external provider unavailable")
    done = ai_scout.scheduler_shadow_tick(
        "2026-10-13", None, runner=failing,
    )
    assert done == "2026-10-13"
    done = ai_scout.scheduler_shadow_tick(
        "2026-10-13", done, runner=failing,
    )
    assert calls == ["2026-10-13"]


def test_new_wat_day_can_run_another_independent_research_review(monkeypatch):
    monkeypatch.setenv("AI_SCOUT_ENABLED", "true")
    days = []
    def run(*, day):
        days.append(day)
        return {"status": "ALREADY_CAPTURED"}
    assert ai_scout.scheduler_shadow_tick(
        "2026-10-14", "2026-10-13", runner=run,
    ) == "2026-10-14"
    assert days == ["2026-10-14"]
