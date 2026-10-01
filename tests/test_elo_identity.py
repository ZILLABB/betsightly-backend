from leagues.elo_identity import (
    canonical_team_key,
    lookup_rating_entry,
)


def test_canonical_key_keeps_squad_boundary():
    assert (
        canonical_team_key("Arsenal")
        != canonical_team_key(
            "Arsenal Women"
        )
    )
    assert (
        canonical_team_key("Ajax")
        != canonical_team_key(
            "Jong Ajax"
        )
    )


def test_exact_provider_name_wins():
    pool = {
        "Manchester United": {
            "rating": 1600,
            "matches": 20,
        }
    }
    result = lookup_rating_entry(
        "Manchester United",
        pool,
    )
    assert result["status"] == "READY"
    assert (
        result["method"]
        == "exact_provider_name"
    )


def test_unique_canonical_fallback_resolves_provider_spelling():
    pool = {
        "Brøndby IF": {
            "rating": 1600,
            "matches": 20,
        }
    }
    result = lookup_rating_entry(
        "Brondby",
        pool,
    )
    assert result["status"] == "READY"
    assert result["method"] in {
        "unique_canonical_match",
        "unique_strict_equivalent",
    }
    assert result["entry"]["rating"] == 1600


def test_unique_strict_equivalent_handles_bounded_suffix_difference():
    pool = {
        "Hamburger SV": {
            "rating": 1600,
            "matches": 20,
        }
    }
    result = lookup_rating_entry(
        "Hamburg",
        pool,
    )
    assert result["status"] == "READY"
    assert (
        result["method"]
        == "unique_strict_equivalent"
    )


def test_strict_equivalent_never_crosses_squad_boundary():
    pool = {
        "Arsenal Women": {
            "rating": 1600,
            "matches": 20,
        }
    }
    result = lookup_rating_entry(
        "Arsenal",
        pool,
    )
    assert result["status"] == "UNAVAILABLE"
    assert result["entry"] is None


def test_multiple_strict_matches_fail_closed():
    pool = {
        "Hamburger SV": {
            "rating": 1600,
            "matches": 20,
        },
        "Hamburg FC": {
            "rating": 1500,
            "matches": 20,
        },
    }
    result = lookup_rating_entry(
        "Hamburg",
        pool,
    )
    assert result["status"] == "AMBIGUOUS"
    assert result["entry"] is None


def test_verified_alias_resolves_ambiguous_provider_name():
    pool = {
        "Cercle Brugge KSV": {
            "rating": 1600,
            "matches": 20,
        },
        "Club Brugge": {
            "rating": 1650,
            "matches": 20,
        },
    }

    result = lookup_rating_entry(
        "Cercle Brugge",
        pool,
    )

    assert result["status"] == "READY"
    assert result["method"] == "verified_alias"
    assert result["candidates"] == ["Cercle Brugge KSV"]


def test_verified_alias_missing_target_fails_closed():
    pool = {
        "Club Brugge": {
            "rating": 1650,
            "matches": 20,
        }
    }

    result = lookup_rating_entry(
        "Cercle Brugge",
        pool,
    )

    assert result["status"] == "UNAVAILABLE"
    assert (
        result["method"]
        == "verified_alias_target_missing"
    )
