"""Protect DNB from backing the model's or bookmaker's weaker side."""
import pytest

from leagues.dnb_strength_policy import dnb_strength_reasons
from leagues.publication_policy import evaluate_leg
from leagues.market_registry import MARKET_TO_SPORTYBET


def _pick(market="dnb_home", home=.56, away=.20,
          home_odds=1.60, away_odds=4.10):
    return {
        "match_id": "fixture-1", "market": market,
        "confidence": .80, "odds": 1.42, "odds_are_real": True,
        "bookable": True, "safe_tier_eligible": True,
        "market_floor_eligible": True, "market_trust_state": "TRUSTED",
        "trust": {"accepted": True, "trust_grade": "A",
                  "evidence_adjusted_probability": .80},
        "_fixture": {"odds": {"home_win": home_odds, "away_win": away_odds},
                     "league_slug": "eng.1", "competition_type": "LEAGUE"},
        "_model": {"probabilities": {"home_win": home,
                                      "away_win": away, "draw": .24}},
    }


def test_live_sportybet_dnb_home_away_outcome_mapping_is_not_reversed():
    assert MARKET_TO_SPORTYBET["dnb_home"] == ("11", "", "4")
    assert MARKET_TO_SPORTYBET["dnb_away"] == ("11", "", "5")


@pytest.mark.parametrize("case", [
    _pick("dnb_home", home=.56, away=.20, home_odds=1.60, away_odds=4.1),
    _pick("dnb_away", home=.20, away=.56, home_odds=4.1, away_odds=1.6),
])
def test_genuine_model_and_bookmaker_favourite_is_allowed(case):
    assert dnb_strength_reasons(case) == []
    assert evaluate_leg(case, "5_odds")["allowed"]


def test_stronger_model_side_but_bookmaker_favours_other_is_blocked():
    pick = _pick("dnb_home", home=.56, away=.20,
                 home_odds=3.10, away_odds=2.15)
    assert "DNB_NOT_BOOKMAKER_FAVOURITE" in dnb_strength_reasons(pick)
    decision = evaluate_leg(pick, "10_odds")
    assert decision["allowed"] is False
    assert "DNB_NOT_BOOKMAKER_FAVOURITE" in decision["reasons"]


def test_away_side_is_not_published_when_model_favours_home():
    pick = _pick("dnb_away", home=.56, away=.20,
                 home_odds=4.1, away_odds=1.6)
    assert "DNB_NOT_MODEL_FAVOURITE" in dnb_strength_reasons(pick)
    assert not evaluate_leg(pick, "2_odds")["allowed"]


def test_missing_1x2_bookmaker_evidence_blocks_dnb_not_other_markets():
    pick = _pick()
    pick["_fixture"]["odds"] = {}
    assert "DNB_BOOKMAKER_STRENGTH_UNVERIFIED" in dnb_strength_reasons(pick)
    assert "DNB_BOOKMAKER_STRENGTH_UNVERIFIED" in evaluate_leg(pick, "5_odds")["reasons"]
    pick["market"] = "over_1_5"
    assert dnb_strength_reasons(pick) == []


def test_persisted_published_game_receives_same_strength_check():
    pick = _pick("dnb_home", home=.56, away=.20,
                 home_odds=3.1, away_odds=2.15)
    converted = {k: v for k, v in pick.items() if k not in ("_fixture", "_model")}
    converted.update(model_home_win_probability=.56,
                     model_away_win_probability=.20,
                     bookmaker_home_win_odds=3.1,
                     bookmaker_away_win_odds=2.15,
                     model_draw_probability=.24)
    assert dnb_strength_reasons(converted) == dnb_strength_reasons(pick)
    assert not evaluate_leg(converted, "5_odds")["allowed"]


def test_tied_favourite_is_not_guessed():
    pick = _pick(home=.35, away=.35, home_odds=2.6, away_odds=2.6)
    assert "DNB_NOT_MODEL_FAVOURITE" in dnb_strength_reasons(pick)
    assert "DNB_NOT_BOOKMAKER_FAVOURITE" in dnb_strength_reasons(pick)


def test_pick_builder_drops_model_bookmaker_dnb_disagreement(monkeypatch):
    from leagues.picks import build_picks
    monkeypatch.setattr(
        "leagues.sportybet.availability_from_fixture",
        lambda fixture, market: {
            "sportybet_available": True, "status": "BOOKABLE",
            "event_id": "fixture",
        },
    )
    fixture = {
        "match_id": "fixture", "home": {"name": "Home"},
        "away": {"name": "Away"},
        "odds": {
            "home_win": 3.10, "away_win": 2.15,
            "dnb_home": 1.40, "dnb_away": 1.80,
            "provider": "SportyBet",
        },
    }
    model = {
        "probabilities": {
            "home_win": .56, "away_win": .20, "draw": .24,
            "dnb_home": .79, "dnb_away": .21,
        }
    }
    candidates = build_picks(fixture, model, min_confidence=.65,
                             fit={"groups": {}})
    assert not any(p["market"] == "dnb_home" for p in candidates)


def test_pick_builder_can_select_agreed_home_favourite(monkeypatch):
    from leagues.picks import build_picks
    monkeypatch.setattr(
        "leagues.sportybet.availability_from_fixture",
        lambda fixture, market: {"sportybet_available": True,
                                 "status": "BOOKABLE"},
    )
    fixture = {
        "match_id": "fixture", "home": {"name": "Home"},
        "away": {"name": "Away"},
        "odds": {"home_win": 1.60, "away_win": 4.10,
                 "dnb_home": 1.32, "dnb_away": 4.10,
                 "provider": "SportyBet"},
    }
    model = {
        "probabilities": {
            "home_win": .56, "away_win": .20, "draw": .24,
            "dnb_home": .78, "dnb_away": .22,
        },
    }
    candidates = build_picks(fixture, model, min_confidence=.65,
                             fit={"groups": {}})
    assert any(p["market"] == "dnb_home" for p in candidates)
