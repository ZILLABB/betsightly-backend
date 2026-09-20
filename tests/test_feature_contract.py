from leagues.feature_contract import (
    FEATURE_COLUMNS,
    FEATURE_SCHEMA_VERSION,
    artifact_compatible,
    build_feature_vector,
)


def _form(prefix):
    return {
        "win_rate_5": .6, "win_rate_10": .55, "draw_rate_5": .2,
        "goals_scored_5": 1.8, "goals_conceded_5": .9,
        "venue_win_rate_5": .7, "venue_goals_5": 2.0,
    }


def test_feature_contract_scales_h2h_and_tier_once_for_all_callers():
    vector = build_feature_vector(
        home_form=_form("home"), away_form=_form("away"),
        h2h={"home_win_rate": .5, "avg_goals": 2.4,
             "btts_rate": .4, "meetings": 1},
        league_tier=1, odds={},
    )
    values = dict(zip(vector.columns, vector.values))
    assert vector.version == FEATURE_SCHEMA_VERSION
    assert vector.columns == FEATURE_COLUMNS
    assert values["h2h_meetings"] == .1
    assert values["league_tier"] == .5
    assert values["mkt_has_odds"] == 0
    assert values["mkt_ou_has"] == 0
    assert values["mkt_prob_over25"] == .52


def test_old_artifact_without_version_is_rejected_instead_of_silently_reused():
    compatible, reason = artifact_compatible({"feature_columns": list(FEATURE_COLUMNS)})
    assert compatible is False
    assert reason == "FEATURE_SCHEMA_VERSION_MISMATCH"


def test_artifact_requires_exact_order_and_version():
    good = {
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "feature_columns": list(FEATURE_COLUMNS),
    }
    assert artifact_compatible(good) == (True, "COMPATIBLE")
    bad = dict(good, feature_columns=list(reversed(FEATURE_COLUMNS)))
    assert artifact_compatible(bad)[1] == "FEATURE_COLUMN_ORDER_MISMATCH"
