"""Historical source registry and training-eligibility policy.

A source can improve football-history coverage without being suitable for the
current market-feature ML ensemble.  Keep those concepts separate.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Iterable


RESULTS_ONLY = "RESULTS_ONLY"
ODDS_BACKED = "ODDS_BACKED"
UNRESOLVED = "UNRESOLVED"

VERIFIED = "VERIFIED"
REVIEW_REQUIRED = "REVIEW_REQUIRED"


@dataclass(frozen=True)
class HistoricalSource:
    league_id: int
    competition: str
    provider: str
    dataset: str
    source_class: str
    verification: str
    license: str | None
    results_history: bool
    bookmaker_odds_history: bool
    source_root: str | None
    notes: str

    def as_dict(self) -> dict:
        return asdict(self)


SOURCES: tuple[HistoricalSource, ...] = (
    HistoricalSource(
        1,
        "FIFA World Cup",
        "OpenFootball",
        "worldcup",
        RESULTS_ONLY,
        VERIFIED,
        "CC0-1.0 / public domain",
        True,
        False,
        "openfootball/worldcup",
        "Historical World Cup fixtures/results. No bookmaker-price provenance.",
    ),
    HistoricalSource(
        2,
        "UEFA Champions League",
        "OpenFootball",
        "champions-league",
        RESULTS_ONLY,
        VERIFIED,
        "CC0-1.0 / public domain",
        True,
        False,
        "openfootball/champions-league",
        "Champions League fixtures/results including qualifiers; no odds history.",
    ),
    HistoricalSource(
        3,
        "UEFA Europa League",
        "OpenFootball",
        "champions-league",
        RESULTS_ONLY,
        VERIFIED,
        "CC0-1.0 / public domain",
        True,
        False,
        "openfootball/champions-league",
        "Europa League fixtures/results; no odds history.",
    ),
    HistoricalSource(
        848,
        "UEFA Conference League",
        "OpenFootball",
        "champions-league",
        RESULTS_ONLY,
        VERIFIED,
        "CC0-1.0 / public domain",
        True,
        False,
        "openfootball/champions-league",
        "Conference League fixtures/results; no odds history.",
    ),
    HistoricalSource(
        13,
        "Copa Libertadores",
        "OpenFootball",
        "south-america/copa-libertadores",
        RESULTS_ONLY,
        VERIFIED,
        "CC0-1.0 / public domain",
        True,
        False,
        "openfootball/south-america",
        "Libertadores fixtures/results; no bookmaker-price provenance.",
    ),
    HistoricalSource(
        11,
        "Copa Sudamericana",
        "OpenFootball",
        "south-america/copa-libertadores",
        RESULTS_ONLY,
        VERIFIED,
        "CC0-1.0 / public domain",
        True,
        False,
        "openfootball/south-america",
        (
            "Sudamericana fixtures/results are ingested from the "
            "verified *_copas.txt series; no bookmaker-price provenance."
        ),
    ),
    HistoricalSource(
        265,
        "Chilean Primera Division",
        "UNRESOLVED",
        "unresolved",
        UNRESOLVED,
        REVIEW_REQUIRED,
        None,
        False,
        False,
        None,
        "Not covered by the current football-data.co.uk country feed registry.",
    ),
    HistoricalSource(
        292,
        "K League 1",
        "UNRESOLVED",
        "unresolved",
        UNRESOLVED,
        REVIEW_REQUIRED,
        None,
        False,
        False,
        None,
        "No verified free source selected yet.",
    ),
    HistoricalSource(
        307,
        "Saudi Pro League",
        "UNRESOLVED",
        "unresolved",
        UNRESOLVED,
        REVIEW_REQUIRED,
        None,
        False,
        False,
        None,
        "No verified free source selected yet.",
    ),
)


def source_for(league_id: int) -> HistoricalSource | None:
    for source in SOURCES:
        if source.league_id == int(league_id):
            return source
    return None


def results_covered_ids() -> set[int]:
    return {source.league_id for source in SOURCES if source.results_history}


def odds_backed_ids() -> set[int]:
    return {source.league_id for source in SOURCES if source.bookmaker_odds_history}


def unresolved_ids() -> set[int]:
    return {
        source.league_id
        for source in SOURCES
        if source.source_class == UNRESOLVED
    }


def eligible_for_current_market_feature_training(source: HistoricalSource) -> bool:
    """Current ensemble uses market-price features; results-only rows are not eligible."""
    return bool(
        source.verification == VERIFIED
        and source.results_history
        and source.bookmaker_odds_history
    )


def summary() -> dict:
    items = [source.as_dict() for source in SOURCES]
    return {
        "tracked_gap_count": len(items),
        "results_history_covered_count": sum(
            1 for source in SOURCES if source.results_history
        ),
        "odds_backed_covered_count": sum(
            1 for source in SOURCES if source.bookmaker_odds_history
        ),
        "current_market_model_eligible_count": sum(
            1 for source in SOURCES
            if eligible_for_current_market_feature_training(source)
        ),
        "unresolved_count": sum(
            1 for source in SOURCES if source.source_class == UNRESOLVED
        ),
        "sources": items,
    }
