"""Conservative cross-provider team identity for Elo lookup.

Resolution order:
1. exact provider name
2. exact squad-aware canonical key
3. unique strict team-equivalence match using the mature SportyBet matcher

Any collision or multiple candidate match fails closed.
"""
from __future__ import annotations

from leagues.canonical_identity import normalize_team
from leagues import sportybet

ELO_IDENTITY_VERSION = "elo-team-identity-v3"

VERIFIED_TEAM_ALIASES = {'Aarhus': 'AGF',
 'Argentinos Jrs': 'Argentinos Juniors',
 'Ath Bilbao': 'Athletic Club',
 'Ath Madrid': 'Atlético Madrid',
 'Atl. San Luis': 'Atlético de San Luis',
 'Atl. Tucuman': 'Atlético Tucumán',
 'Atlanta Utd': 'Atlanta United FC',
 'BW Linz': 'FC Blau-Weiß Linz',
 'Bodrumspor': 'Bodrum FK',
 'Buyuksehyr': 'Istanbul Basaksehir',
 'Cercle Brugge': 'Cercle Brugge KSV',
 'DC United': 'D.C. United',
 'Dep. Riestra': 'Deportivo Riestra',
 'Ein Frankfurt': 'Eintracht Frankfurt',
 'Espanol': 'Espanyol',
 'Estudiantes L.P.': 'Estudiantes de La Plata',
 'FC Copenhagen': 'F.C. København',
 'FC Koln': 'FC Cologne',
 'For Sittard': 'Fortuna Sittard',
 'Ind. Rivadavia': 'Independiente Rivadavia',
 'Larisa': 'Larissa FC',
 'Levadeiakos': 'Levadiakos',
 "M'gladbach": 'Borussia Mönchengladbach',
 'Man United': 'Manchester United',
 'New York Red Bulls': 'Red Bull New York',
 'Newells Old Boys': "Newell's Old Boys",
 "Nott'm Forest": 'Nottingham Forest',
 'Olympiakos': 'Olympiacos',
 'Preston': 'Preston North End',
 'QPR': 'Queens Park Rangers',
 'Rennes': 'Stade Rennais',
 'Sheffield Weds': 'Sheffield Wednesday',
 'Sp Lisbon': 'Sporting CP',
 'U. Cluj': 'Universitatea Cluj',
 'West Brom': 'West Bromwich Albion'}



def canonical_team_key(name: str) -> str:
    raw = str(name or "")
    normalized = normalize_team(raw)
    squad = sportybet._squad(raw) or "senior"
    if not normalized:
        return ""
    return f"{squad}:{normalized}"


def _squad(name: str) -> str:
    return sportybet._squad(str(name or "")) or "senior"


def canonical_rating_index(pool: dict) -> tuple[dict, set[str]]:
    index = {}
    ambiguous: set[str] = set()

    for raw_name, entry in (pool or {}).items():
        if not isinstance(entry, dict):
            continue
        key = canonical_team_key(raw_name)
        if not key:
            continue
        if key not in index:
            index[key] = entry
        elif index[key] is not entry and index[key] != entry:
            ambiguous.add(key)

    for key in ambiguous:
        index.pop(key, None)

    return index, ambiguous


def _strict_equivalent_candidates(
    team_name: str,
    pool: dict,
) -> list[tuple[str, dict]]:
    target_norm = normalize_team(team_name)
    target_squad = _squad(team_name)
    if not target_norm:
        return []

    matches = []
    for raw_name, entry in (pool or {}).items():
        if not isinstance(entry, dict):
            continue
        if _squad(raw_name) != target_squad:
            continue

        candidate_norm = normalize_team(raw_name)
        if not candidate_norm:
            continue

        if sportybet._same_team(
            target_norm,
            candidate_norm,
        ):
            matches.append(
                (str(raw_name), entry)
            )

    return matches


def lookup_rating_entry(team_name: str, pool: dict) -> dict:
    """Resolve one team against one league-scoped rating pool.

    Priority:
    1. exact provider name
    2. verified provider alias
    3. unique canonical/strict equivalence

    Verified aliases are authoritative. If their target is absent from the
    current league pool, resolution fails closed rather than falling through
    to a potentially wrong fuzzy-equivalent club.
    """
    key = canonical_team_key(team_name)

    if not isinstance(pool, dict):
        return {
            "status": "UNAVAILABLE",
            "entry": None,
            "method": "invalid_pool",
            "canonical_key": key,
            "candidates": [],
        }

    exact = pool.get(team_name)
    if isinstance(exact, dict):
        return {
            "status": "READY",
            "entry": exact,
            "method": "exact_provider_name",
            "canonical_key": key,
            "candidates": [str(team_name)],
        }

    alias_target = VERIFIED_TEAM_ALIASES.get(team_name)

    if alias_target is not None:
        alias_entry = pool.get(alias_target)

        if isinstance(alias_entry, dict):
            return {
                "status": "READY",
                "entry": alias_entry,
                "method": "verified_alias",
                "canonical_key": key,
                "candidates": [alias_target],
            }

        return {
            "status": "UNAVAILABLE",
            "entry": None,
            "method": "verified_alias_target_missing",
            "canonical_key": key,
            "candidates": [alias_target],
        }

    if not key:
        return {
            "status": "UNAVAILABLE",
            "entry": None,
            "method": "empty_identity",
            "canonical_key": key,
            "candidates": [],
        }

    candidates = {}

    canonical_index, canonical_ambiguous = canonical_rating_index(pool)

    if key in canonical_ambiguous:
        return {
            "status": "AMBIGUOUS",
            "entry": None,
            "method": "canonical_collision",
            "canonical_key": key,
            "candidates": [],
        }

    canonical_entry = canonical_index.get(key)

    if canonical_entry is not None:
        for raw_name, entry in pool.items():
            if (
                isinstance(entry, dict)
                and canonical_team_key(raw_name) == key
            ):
                candidates.setdefault(
                    str(raw_name),
                    [entry, set()],
                )[1].add("canonical")

    for raw_name, entry in _strict_equivalent_candidates(
        team_name,
        pool,
    ):
        candidates.setdefault(
            str(raw_name),
            [entry, set()],
        )[1].add("strict")

    if len(candidates) > 1:
        return {
            "status": "AMBIGUOUS",
            "entry": None,
            "method": "multiple_identity_candidates",
            "canonical_key": key,
            "candidates": sorted(candidates),
        }

    if len(candidates) == 1:
        raw_name, value = next(iter(candidates.items()))
        entry, methods = value

        method = (
            "unique_canonical_match"
            if "canonical" in methods
            else "unique_strict_equivalent"
        )

        return {
            "status": "READY",
            "entry": entry,
            "method": method,
            "canonical_key": key,
            "candidates": [raw_name],
        }

    return {
        "status": "UNAVAILABLE",
        "entry": None,
        "method": "no_strict_match",
        "canonical_key": key,
        "candidates": [],
    }
