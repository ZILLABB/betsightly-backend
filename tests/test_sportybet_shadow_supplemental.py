from datetime import (
    datetime,
    timedelta,
    timezone,
)
from types import SimpleNamespace

from leagues import sportybet


def _entry(
    *,
    event_id="1",
    home="Arsenal",
    away="Chelsea",
    competition="Premier League",
    kickoff=None,
    prices=None,
):
    kickoff = kickoff or datetime(
        2026,
        9,
        30,
        18,
        tzinfo=timezone.utc,
    )

    return {
        "event_id": event_id,
        "home_team": home,
        "away_team": away,
        "home_squad": "",
        "away_squad": "",
        "kickoff_ms": int(
            kickoff.timestamp()
            * 1000
        ),
        "competition": competition,
        "prices": (
            prices
            or {
                "over_1_5": 1.35,
            }
        ),
        "margins": {},
        "market_refs": {},
    }


def _board(entry):
    key = (
        f"{sportybet._norm(entry['home_team'])}|"
        f"{sportybet._norm(entry['away_team'])}"
    )

    return {
        "__meta__": {
            "snapshot_id": "shadow-board",
            "is_complete": True,
        },
        key: [entry],
    }


def _history(
    home="Arsenal",
    away="Chelsea",
):
    return SimpleNamespace(
        by_team={
            (
                "CLUB",
                home,
            ): [{} for _ in range(5)],
            (
                "CLUB",
                away,
            ): [{} for _ in range(6)],
        }
    )


def test_exact_mapped_sportybet_only_fixture_can_become_shadow_ready():
    now = datetime(
        2026,
        9,
        30,
        12,
        tzinfo=timezone.utc,
    )

    entry = _entry(
        kickoff=now
        + timedelta(hours=6)
    )

    live_fixtures = []

    report = (
        sportybet.shadow_supplemental_readiness(
            live_fixtures,
            _board(entry),
            cached_rates={
                "eng.1": {
                    "matches": 20,
                }
            },
            history=_history(),
            now=now,
            days_ahead=3,
        )
    )

    assert (
        report["ready_for_shadow_model_count"]
        == 1
    )

    assert (
        report["samples"][0]["readiness"]
        == "READY_FOR_SHADOW_MODEL"
    )

    assert (
        report["samples"][0][
            "competition_history_matches"
        ]
        == 20
    )

    assert (
        report["samples"][0][
            "home_history"
        ]["matches"]
        == 5
    )

    assert report["predictor_invoked"] is False
    assert report["publishing_changed"] is False
    assert report["prediction_pool_changed"] is False

    # No supplemental match was inserted into the live fixture list.
    assert live_fixtures == []


def test_known_competition_with_thin_history_stays_shadow_unready():
    now = datetime(
        2026,
        9,
        30,
        12,
        tzinfo=timezone.utc,
    )

    entry = _entry(
        kickoff=now
        + timedelta(hours=4)
    )

    report = (
        sportybet.shadow_supplemental_readiness(
            [],
            _board(entry),
            cached_rates={
                "eng.1": {
                    "matches": 3,
                }
            },
            history=_history(),
            now=now,
            days_ahead=3,
        )
    )

    assert (
        report["ready_for_shadow_model_count"]
        == 0
    )

    assert (
        report["samples"][0]["readiness"]
        == "INSUFFICIENT_COMPETITION_HISTORY"
    )


def test_normalized_team_alias_can_resolve_existing_history_without_fuzzy_guessing():
    now = datetime(
        2026,
        9,
        30,
        12,
        tzinfo=timezone.utc,
    )

    entry = _entry(
        home="Man Utd",
        away="Chelsea",
        kickoff=now
        + timedelta(hours=5),
    )

    history = _history(
        home="Manchester United",
        away="Chelsea",
    )

    report = (
        sportybet.shadow_supplemental_readiness(
            [],
            _board(entry),
            cached_rates={
                "eng.1": {
                    "matches": 30,
                }
            },
            history=history,
            now=now,
            days_ahead=3,
        )
    )

    sample = report["samples"][0]

    assert (
        sample["readiness"]
        == "READY_FOR_SHADOW_MODEL"
    )

    assert (
        sample["home_history"]["team"]
        == "Manchester United"
    )



def test_readiness_report_groups_blockers_without_changing_matching():
    now = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)
    ready_entry = _entry(
        event_id="ready",
        kickoff=now + timedelta(hours=4),
    )
    missing_entry = _entry(
        event_id="missing",
        home="Unknown Town",
        away="Chelsea",
        kickoff=now + timedelta(hours=5),
    )
    board = _board(ready_entry)
    missing_key = (
        f"{sportybet._norm(missing_entry['home_team'])}|"
        f"{sportybet._norm(missing_entry['away_team'])}"
    )
    board[missing_key] = [missing_entry]

    report = sportybet.shadow_supplemental_readiness(
        [],
        board,
        cached_rates={"eng.1": {"matches": 30}},
        history=_history(),
        now=now,
        days_ahead=3,
    )

    assert report["readiness_counts"]["READY_FOR_SHADOW_MODEL"] == 1
    assert report["readiness_counts"]["TEAM_IDENTITY_NOT_READY"] == 1
    assert report["readiness_by_league"]["eng.1"]["evaluated"] == 2
    assert len(report["identity_not_ready_samples"]) == 1
    assert report["identity_not_ready_samples"][0]["home_team"] == "Unknown Town"
