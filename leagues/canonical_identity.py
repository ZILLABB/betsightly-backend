"""Strict canonical identity resolution for provider fixtures.

Resolution is deliberately conservative. A wrong canonical mapping is worse
than an unresolved fixture, because it can attach prices/data to the wrong game.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher

from leagues import sportybet

EXACT_ID = "EXACT_ID"
EXACT_ALIAS = "EXACT_ALIAS"
TEAM_KICKOFF = "TEAM_KICKOFF"
FUZZY_VERIFIED = "FUZZY_VERIFIED"
AMBIGUOUS = "AMBIGUOUS"
UNMATCHED = "UNMATCHED"

_KICKOFF_TOLERANCE_MINUTES = 45.0
_FUZZY_MIN = 0.92
_FUZZY_MARGIN = 0.08


@dataclass(frozen=True)
class FixtureIdentity:
    state: str
    canonical_fixture_id: str | None
    confidence: float
    method: str
    candidates: tuple[str, ...] = ()
    reason: str | None = None

    def as_dict(self) -> dict:
        return {
            "state": self.state,
            "canonical_fixture_id": self.canonical_fixture_id,
            "confidence": round(float(self.confidence), 4),
            "method": self.method,
            "candidates": list(self.candidates),
            "reason": self.reason,
        }


def normalize_team(name: str) -> str:
    return sportybet._norm(name or "")


def normalize_competition(name: str) -> str:
    """Competition-specific normalization shared with the mature matcher.

    Team normalization intentionally removes club-noise words; competition
    normalization must not do that because words such as "league", "division",
    and country qualifiers carry identity.
    """
    return sportybet._norm_competition(name or "")


# Verified provider-name equivalences observed on the live SportyBet/ESPN
# shadow parity audit. These are deliberately pair-specific rather than broad
# aliases: generic labels such as "Primera Division", "Championship", and
# "Liga Nacional" remain valid only against the exact verified competition
# names below, while team/squad/kickoff guards still have to pass.
_COMPETITION_EQUIVALENT_PAIRS = {
    frozenset(("laliga 2", "laliga hypermotion")),
    frozenset(("efl league two", "league two")),
    frozenset(("brasileirao serie b", "brasileiro serie b")),
    frozenset(("categoria primera a", "liga dimayor")),
    frozenset(("primera division uruguay", "primera division")),
    frozenset(("international friendly", "int friendly games")),
    frozenset(("liga profesional argentina", "primera lpf")),
    frozenset(("efl league one", "league one")),
    frozenset(("nwsl", "national womens soccer league")),
    frozenset(("scottish championship", "championship")),
    frozenset(("brasileirao serie a", "brasileiro serie a")),
    frozenset(("division profesional paraguay", "division de honor")),
    frozenset(("liga nacional guatemala", "liga nacional")),
    frozenset(("primera division el salvador", "primera division")),
    frozenset(("liga 1 peru", "liga 1")),
    frozenset(("primera division chile", "primera division")),
}


def _kickoff(value) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        try:
            dt = datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            return None
    elif isinstance(value, str) and value:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _kickoff_delta_minutes(left, right) -> float | None:
    a = _kickoff(left)
    b = _kickoff(right)
    if a is None or b is None:
        return None
    return abs((a - b).total_seconds()) / 60.0


def _team_score(provider_name: str, canonical_name: str) -> float:
    left = normalize_team(provider_name)
    right = normalize_team(canonical_name)
    if not left or not right:
        return 0.0
    if left == right or sportybet._same_team(left, right):
        return 1.0
    return SequenceMatcher(a=left, b=right).ratio()


def _competition_matches(provider_name: str, canonical_name: str) -> bool:
    left = normalize_competition(provider_name)
    right = normalize_competition(canonical_name)
    if not left or not right or left == right:
        return True
    return frozenset((left, right)) in _COMPETITION_EQUIVALENT_PAIRS


def _fixture_score(provider_fixture: dict, canonical_fixture: dict) -> tuple[float, str] | None:
    if (
        sportybet._squad(provider_fixture.get("home_team") or "")
        != sportybet._squad(canonical_fixture.get("home_team") or "")
        or sportybet._squad(provider_fixture.get("away_team") or "")
        != sportybet._squad(canonical_fixture.get("away_team") or "")
    ):
        return None

    delta = _kickoff_delta_minutes(
        provider_fixture.get("kickoff") or provider_fixture.get("kickoff_ms"),
        canonical_fixture.get("kickoff"),
    )
    if delta is None or delta > _KICKOFF_TOLERANCE_MINUTES:
        return None

    home = _team_score(
        provider_fixture.get("home_team") or "",
        canonical_fixture.get("home_team") or "",
    )
    away = _team_score(
        provider_fixture.get("away_team") or "",
        canonical_fixture.get("away_team") or "",
    )
    if not _competition_matches(
        provider_fixture.get("competition") or "",
        canonical_fixture.get("competition") or "",
    ):
        return None

    if home == 1.0 and away == 1.0:
        return 1.0, TEAM_KICKOFF

    if min(home, away) < _FUZZY_MIN:
        return None

    confidence = min(home, away) * max(0.0, 1.0 - delta / 180.0)
    return confidence, FUZZY_VERIFIED


def resolve_fixture(
    provider_fixture: dict,
    canonical_fixtures: list[dict],
    *,
    provider_mapping: dict | None = None,
    aliases: dict[str, str] | None = None,
) -> dict:
    """Resolve one provider fixture; ambiguous/weak matches fail closed."""
    provider_mapping = provider_mapping or {}
    aliases = aliases or {}

    provider_fixture_id = str(
        provider_fixture.get("sportybet_event_id")
        or provider_fixture.get("event_id")
        or provider_fixture.get("provider_fixture_id")
        or ""
    )
    mapped_id = provider_mapping.get(provider_fixture_id)
    if mapped_id:
        exists = any(
            str(item.get("id")) == str(mapped_id)
            for item in canonical_fixtures
        )
        if exists:
            return FixtureIdentity(
                state=EXACT_ID,
                canonical_fixture_id=str(mapped_id),
                confidence=1.0,
                method="verified_provider_mapping",
            ).as_dict()

    fixture = dict(provider_fixture)
    for side in ("home_team", "away_team"):
        normalized = normalize_team(fixture.get(side) or "")
        alias_target = aliases.get(normalized)
        if alias_target:
            fixture[side] = alias_target

    matches: list[tuple[float, str, dict]] = []
    for candidate in canonical_fixtures:
        scored = _fixture_score(fixture, candidate)
        if scored is None:
            continue
        score, method = scored
        matches.append((score, method, candidate))

    if not matches:
        return FixtureIdentity(
            state=UNMATCHED,
            canonical_fixture_id=None,
            confidence=0.0,
            method="none",
            reason="no_candidate_passed_identity_guards",
        ).as_dict()

    matches.sort(key=lambda item: item[0], reverse=True)
    best_score, best_method, best = matches[0]
    candidate_ids = tuple(str(item[2].get("id")) for item in matches[:5])

    if len(matches) > 1:
        second_score = matches[1][0]
        if (
            best_score < 1.0
            and best_score - second_score < _FUZZY_MARGIN
        ):
            return FixtureIdentity(
                state=AMBIGUOUS,
                canonical_fixture_id=None,
                confidence=best_score,
                method="ambiguous_candidates",
                candidates=candidate_ids,
                reason="top_candidates_too_close",
            ).as_dict()

        if best_score == 1.0 and second_score == 1.0:
            return FixtureIdentity(
                state=AMBIGUOUS,
                canonical_fixture_id=None,
                confidence=1.0,
                method="duplicate_exact_identity",
                candidates=candidate_ids,
                reason="multiple_exact_candidates",
            ).as_dict()

    state = EXACT_ALIAS if aliases and best_method == TEAM_KICKOFF else best_method
    return FixtureIdentity(
        state=state,
        canonical_fixture_id=str(best.get("id")),
        confidence=best_score,
        method=best_method,
        candidates=(str(best.get("id")),),
    ).as_dict()
