"""Six non-NBA league source catalog and explicit permission gates.

A reachable public endpoint is not a commercial data licence. This module
never transfers source statistics into football, betting or NBA forecasts.
"""
from __future__ import annotations

from basketball.research_multileague_release_gates import CANDIDATE_LEAGUES
from basketball.research_other_league_sources import CANDIDATES, source_url
from basketball.research_europe_sources import EUROPE, source_url as europe_url

# Rights summaries are compliance flags, NOT a substitute for counsel or a grant.
SOURCES = {
    "wnba": {
        "provider": "espn_site_candidate", "source_kind": "daily_scoreboard",
        "rights": "https://www.wnba.com/terms-of-use",
        "official_reference": "https://www.wnba.com/schedule",
        "needs": "Commercial basketball-statistics and gambling-use permission.",
        "independent_verifier": "WNBA official scoreboard (rights review required)",
    },
    "ncaa_men": {
        "provider": "espn_site_candidate", "source_kind": "daily_scoreboard",
        "rights": "https://www.ncaa.com/tos",
        "official_reference": "https://www.ncaa.com/scoreboard/basketball-men/d1",
        "needs": "NCAA commercial rights plus school identity and division mapping.",
        "independent_verifier": "NCAA scoreboard (terms/consent review required)",
    },
    "ncaa_women": {
        "provider": "espn_site_candidate", "source_kind": "daily_scoreboard",
        "rights": "https://www.ncaa.com/tos",
        "official_reference": "https://www.ncaa.com/scoreboard/basketball-women/d1",
        "needs": "NCAA commercial rights plus school identity and division mapping.",
        "independent_verifier": "NCAA scoreboard (terms/consent review required)",
    },
    "euroleague": {
        "provider": "euroleague_v2_candidate", "source_kind": "season_listing",
        "rights": "https://inform.euroleague.net/terms",
        "official_reference": "https://www.euroleaguebasketball.net/euroleague/",
        "needs": "Written Euroleague rights for commercial statistics and gambling use.",
        "independent_verifier": "Independent season/final scoreboard provider under licence",
    },
    "eurocup": {
        "provider": "euroleague_v2_candidate", "source_kind": "season_listing",
        "rights": "https://inform.euroleague.net/terms",
        "official_reference": "https://www.euroleaguebasketball.net/eurocup/",
        "needs": "Written Euroleague rights for commercial statistics and gambling use.",
        "independent_verifier": "Independent season/final scoreboard provider under licence",
    },
    "nbl_au": {
        "provider": "espn_site_candidate", "source_kind": "daily_scoreboard",
        "rights": "https://www.nbl.com.au/",
        "official_reference": "https://www.nbl.com.au/schedule",
        "needs": "NBL/ESPN data-use clearance and verified independent fixture identities.",
        "independent_verifier": "Official NBL schedule and results (rights review required)",
    },
}

def source_matrix(*, day="20261028", start_year=2026):
    if set(SOURCES) != set(CANDIDATE_LEAGUES):
        raise ValueError("BASKETBALL_CATALOG_RELEASE_LEAGUES_MISMATCH")
    if set(CANDIDATES) | set(EUROPE) != set(CANDIDATE_LEAGUES):
        raise ValueError("BASKETBALL_CATALOG_ADAPTERS_INCOMPLETE")
    result = []
    for league in CANDIDATE_LEAGUES:
        row = SOURCES[league]
        url = (source_url(league, day) if league in CANDIDATES
               else europe_url(league, start_year))
        result.append({
            "league": league, "provider": row["provider"],
            "source_kind": row["source_kind"],
            "candidate_read_url": url, "rights_reference": row["rights"],
            "official_reference": row["official_reference"],
            "required_clearance": row["needs"],
            "independent_verifier": row["independent_verifier"],
            "source_probe_implemented": True,
            "reachable_now": None,  # Never infer network reachability.
            "full_season_complete": False,
            "commercial_training_approved": False,
            "commercial_predictions_approved": False,
            "commercial_settlement_approved": False,
            "research_only": True, "not_bookable": True,
        })
    return {
        "status": "six_league_source_inventory",
        "leagues": result, "source_candidates": len(result),
        "commercially_approved_leagues": 0,
        "research_only": True, "not_bookable": True,
        "independent_cross_source_agreement_proven": False,
    }
