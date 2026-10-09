"""Verified provider IDs expand candidate modeling without fuzzy league joins."""
import pytest

from leagues import sportybet


@pytest.mark.parametrize("competition,tournament_id,category_id,slug", [
    ("J1 League", "sr:tournament:196", "sr:category:52", "jpn.1"),
    ("K-League 1", "sr:tournament:410", "sr:category:291", "kor.1"),
    ("Chinese Super League", "sr:tournament:649", "sr:category:99", "chn.1"),
    ("Saudi Pro League", "sr:tournament:955", "sr:category:310", "sau.1"),
    ("Stars League", "sr:tournament:825", "sr:category:353", "qat.1"),
    ("Pro League", "sr:tournament:915", "sr:category:301", "irn.1"),
])
def test_exact_provider_id_resolves_existing_competition(
    competition, tournament_id, category_id, slug,
):
    result = sportybet.registry_competition_match(
        competition, tournament_id=tournament_id, category_id=category_id,
    )
    assert result["status"] == "MAPPED_EXACT"
    assert result["league_slug"] == slug
    assert result["match_basis"] == "sportybet_provider_identity"


@pytest.mark.parametrize("competition,tournament_id,category_id", [
    ("K-League 1 SRL", "sr:tournament:36225", "sr:category:2123"),
    ("Ligue 2", "sr:tournament:14321", "sr:category:304"),
    ("Stars League", "sr:tournament:825", "sr:category:301"),
    ("Saudi Pro League", "sr:tournament:955", "sr:category:999"),
])
def test_unverified_synthetic_other_country_and_category_joins_stay_blocked(
    competition, tournament_id, category_id,
):
    result = sportybet.registry_competition_match(
        competition, tournament_id=tournament_id, category_id=category_id,
    )
    assert result["status"] == "UNMAPPED"
    assert result["league_slug"] is None
