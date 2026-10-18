"""Market availability diagnostics: don't confuse a disabled market with no fixtures.

The public registry stays authoritative. These tests intentionally DO NOT
promote BTTS or manufacture short-priced Over 0.5 selections.
"""
from leagues.builder_v2 import _market_availability
from leagues.market_registry import MARKETS


def _availability(market, *, raw=0, after_trust=0, approved=0, selected=0, target=5):
    return _market_availability(
        {"market_counts": {
            "after_user_raw_filters": {market: raw},
            "after_trust_and_policy": {market: after_trust},
            "approved": {market: approved},
        }},
        {"requested_markets": [market],
         "target_distribution": {market: target},
         "delivered_distribution": {market: selected}},
    )[market]


def test_btts_yes_reports_disabled_not_fixture_shortage():
    assert MARKETS["btts_yes"].activation != "ACTIVE"
    status = _availability("btts_yes")
    assert status["primary_reason"] == "MARKET_NOT_ACTIVE"
    assert status["automatic_builder_eligible"] is False
    assert status["exact_bookmaker_market_mapped"] is True


def test_btts_no_reports_disabled_not_fixture_shortage():
    status = _availability("btts_no")
    assert status["primary_reason"] == "MARKET_NOT_ACTIVE"
    assert status["automatic_builder_eligible"] is False


def test_over_half_can_be_active_and_still_have_no_approved_games():
    assert MARKETS["over_0_5"].activation == "ACTIVE"
    status = _availability("over_0_5")
    assert status["registry_activation"] == "ACTIVE"
    assert status["automatic_builder_eligible"] is True
    assert status["exact_bookmaker_market_mapped"] is True
    assert status["primary_reason"] == "NO_RAW_CANDIDATES"


def test_over_half_reports_stage_at_which_eligibility_fails():
    assert _availability("over_0_5", raw=7)["primary_reason"] == "TRUST_OR_MARKET_POLICY_REJECTED"
    assert _availability("over_0_5", raw=7, after_trust=3)["primary_reason"] == "BELOW_FINAL_BUILDER_GATES"
    assert _availability("over_0_5", raw=7, after_trust=3, approved=2)["primary_reason"] == "INSUFFICIENT_APPROVED_SELECTIONS"


def test_unsupported_market_not_misreported_as_no_games():
    status = _availability("invented_market")
    assert status["primary_reason"] == "UNKNOWN_MARKET"
    assert status["registry_activation"] == "UNKNOWN"
    assert status["automatic_builder_eligible"] is False
