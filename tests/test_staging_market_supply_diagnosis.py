"""Per-market diagnostics distinguish model production from official eligibility."""
import pytest

from scripts import diagnose_staging_market_supply as diagnostic


def _candidate(market: str, *, fixture: str, real: bool, bookable: bool,
               evidence: bool) -> dict:
    return {
        "market": market, "match_id": fixture,
        "odds_are_real": real, "bookable": bookable,
        "safe_tier_eligible": evidence, "market_floor_eligible": True,
        "_fixture": {"commence_time": "2099-01-01T18:00:00Z"},
    }


def test_market_counts_keep_restricted_and_duplicate_fixture_separate(monkeypatch):
    from leagues import fixture_ranker, publication_policy

    picks = [
        _candidate("over_1_5", fixture="a", real=True,
                   bookable=True, evidence=True),
        _candidate("home_or_draw", fixture="a", real=True,
                   bookable=False, evidence=False),
        _candidate("btts_yes", fixture="b", real=False,
                   bookable=False, evidence=False),
    ]
    def rank(raw, *, include_all_eligible=False):
        assert include_all_eligible is True
        return [p for p in raw if p["market"] != "btts_yes"]
    def gate(pick, product):
        assert product == "5_odds"
        if pick["market"] == "over_1_5":
            return {"allowed": True, "reasons": []}
        return {
            "allowed": False,
            "reasons": ["INSUFFICIENT_SETTLED_EVIDENCE", "NOT_EXACTLY_BOOKABLE"],
        }

    monkeypatch.setattr(fixture_ranker, "canonical_fixture_recommendations", rank)
    monkeypatch.setattr(publication_policy, "evaluate_leg", gate)
    report = diagnostic.inspect_day("2026-10-10", picks)

    assert report["raw_candidates"] == 3
    assert report["raw_fixtures"] == 2
    assert report["post_market_trust_candidates"] == 2
    assert report["post_official_policy_qualified"] == 1
    assert report["markets"]["over_1_5"]["quality_qualified_fixtures"] == 1
    assert report["markets"]["home_or_draw"]["official_rejection_reasons"] == {
        "INSUFFICIENT_SETTLED_EVIDENCE": 1, "NOT_EXACTLY_BOOKABLE": 1,
    }
    assert report["markets"]["btts_yes"]["lost_before_official_policy"] == 1
    assert report["markets"]["btts_yes"]["quality_qualified_selections"] == 0


def test_refuses_a_stale_staging_board(monkeypatch):
    from leagues import engine

    monkeypatch.setattr(diagnostic, "preflight", lambda: "betsightly_db_staging")
    monkeypatch.setattr(engine, "prepared_board", lambda days_ahead: (
        [], [], {"ready": True, "stale": True}
    ))
    with pytest.raises(RuntimeError, match="not fresh"):
        diagnostic.diagnose()


def test_staging_diagnosis_is_read_only_and_has_provenance(monkeypatch):
    from leagues import engine

    monkeypatch.setattr(diagnostic, "preflight", lambda: "betsightly_db_staging")
    picks = [_candidate("over_1_5", fixture="a", real=True,
                        bookable=True, evidence=True)]
    monkeypatch.setattr(engine, "prepared_board", lambda days_ahead: (
        picks, [picks[0]["_fixture"]],
        {"ready": True, "stale": False, "board_snapshot_id": "snapshot",
         "age_seconds": 121, "degraded": True},
    ))
    monkeypatch.setattr(diagnostic, "inspect_day", lambda date, date_picks: {
        "fixture_date_wat": date,
        "markets": {
            "over_1_5": {
                "raw_candidates": 1,
                "real_price_candidates": 1,
                "bookable_candidates": 1,
                "safe_evidence_candidates": 1,
                "market_floor_candidates": 1,
                "retained_after_market_trust": 1,
                "lost_before_official_policy": 0,
                "quality_qualified_selections": 1,
                "official_rejection_reasons": {},
            }
        },
    })
    result = diagnostic.diagnose()
    assert result["database"] == "betsightly_db_staging"
    assert result["snapshot_id"] == "snapshot"
    assert result["source_refresh_triggered"] is False
    assert result["official_publication"] is False
    assert result["quality_thresholds_changed"] is False
    assert result["total_by_market"]["over_1_5"]["quality_qualified_selections"] == 6
