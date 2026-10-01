from leagues.football_first_runtime_core import (
    RUNTIME_FEATURE_COLUMNS,
)
from leagues.football_first_runtime_elo import (
    ELO_IDENTITY_PARITY_LEAGUE_IDS,
    RUNTIME_ELO_FEATURE_COLUMNS,
)
from leagues.football_first_runtime_v2 import (
    BASE_COLUMNS,
    REST_COLUMNS,
    V2_CANDIDATE_FEATURE_COLUMNS,
    V2_CANDIDATE_VERSION,
    VENUE_COLUMNS,
)


def test_v2_candidate_is_exactly_32_features():
    assert V2_CANDIDATE_FEATURE_COLUMNS == [
        *RUNTIME_FEATURE_COLUMNS,
        *RUNTIME_ELO_FEATURE_COLUMNS,
        *BASE_COLUMNS,
        *VENUE_COLUMNS,
    ]

    assert len(
        V2_CANDIDATE_FEATURE_COLUMNS
    ) == 32


def test_v2_candidate_excludes_rest_features():
    assert not (
        set(
            V2_CANDIDATE_FEATURE_COLUMNS
        )
        & set(
            REST_COLUMNS
        )
    )


def test_v2_candidate_version_is_frozen():
    assert (
        V2_CANDIDATE_VERSION
        == "football-first-runtime-v2-candidate-32-v1"
    )


def test_identity_fail_closed_leagues_remain_excluded():
    assert 244 not in ELO_IDENTITY_PARITY_LEAGUE_IDS
    assert 283 not in ELO_IDENTITY_PARITY_LEAGUE_IDS
