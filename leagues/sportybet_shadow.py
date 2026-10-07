"""Shadow modelling for SportyBet-only fixtures.

This module is deliberately isolated from the public prediction pool.

A fixture reaches this module only after Batch 6B proves that its competition
is exactly known, both teams resolve to existing ESPN history, sufficient
competition/team history exists, and SportyBet has supported real prices.

SportyBet prices remain output/quality evidence. They are NOT converted into
the predictor's `implied` probability inputs here. Doing so would change the
prediction regime and make the same bookmaker both the probability anchor and
the price benchmark.

Nothing returned here is publishable, bookable by the user, settled
officially, or inserted into the Builder pool.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from statistics import median
from typing import Any

from leagues.base_rates import rates_for
from leagues.competition_registry import competition_for
from leagues.elo_engine import (
    probabilities_for_fixture,
    recent_league_ratings,
)
from leagues.fixture_ranker import canonical_fixture_recommendations
from leagues.picks import MIN_CANDIDATE_CONFIDENCE, build_picks
from leagues.predictor import predict


MAX_SHADOW_FIXTURES = 120


def _board_entries(board: dict | None):
    for key, value in (
        board or {}
    ).items():
        if str(key).startswith("__"):
            continue

        if isinstance(value, list):
            for entry in value:
                if isinstance(
                    entry,
                    dict,
                ):
                    yield entry

        elif isinstance(value, dict):
            yield value


def _board_meta(
    board: dict | None,
) -> dict:
    return dict(
        (
            board
            or {}
        ).get(
            "__meta__"
        )
        or {}
    )


def _entry_index(
    board: dict | None,
) -> dict[str, dict]:
    return {
        str(
            entry.get("event_id")
            or ""
        ): entry
        for entry in _board_entries(
            board
        )
        if str(
            entry.get("event_id")
            or ""
        )
    }


def _kickoff_iso(
    entry: dict,
) -> str | None:
    try:
        return datetime.fromtimestamp(
            float(
                entry.get(
                    "kickoff_ms"
                )
            )
            / 1000.0,
            tz=timezone.utc,
        ).isoformat()

    except (
        TypeError,
        ValueError,
        OSError,
    ):
        return None


def _shadow_fixture(
    sample: dict,
    entry: dict,
    board_meta: dict,
) -> dict | None:
    """Construct an ESPN-compatible fixture without inventing evidence."""
    slug = str(
        sample.get(
            "league_slug"
        )
        or ""
    )

    competition = competition_for(
        slug
    )

    if competition is None:
        return None

    # For this first shadow experiment we only model ordinary league fixtures.
    # Cups/knockouts can be neutral, multi-leg or extra-time affected and the
    # SportyBet board does not carry enough stage context to reconstruct those
    # facts safely.
    if (
        competition.competition_type
        != "LEAGUE"
        or competition.format
        != "LEAGUE"
        or competition.possible_neutral_venue
    ):
        return None

    home_history = (
        sample.get(
            "home_history"
        )
        or {}
    )

    away_history = (
        sample.get(
            "away_history"
        )
        or {}
    )

    home = str(
        home_history.get(
            "team"
        )
        or ""
    ).strip()

    away = str(
        away_history.get(
            "team"
        )
        or ""
    ).strip()

    kickoff = _kickoff_iso(
        entry
    )

    if (
        not home
        or not away
        or not kickoff
    ):
        return None

    odds = {
        **dict(
            entry.get(
                "prices"
            )
            or {}
        ),
        "provider": "SportyBet",
        "margins": dict(
            entry.get(
                "margins"
            )
            or {}
        ),
        "sportybet_event_id": entry.get(
            "event_id"
        ),
        "sportybet_market_refs": deepcopy(
            entry.get(
                "market_refs"
            )
            or {}
        ),
        "sportybet_competition": entry.get(
            "competition"
        ),
        "sportybet_snapshot_id": (
            board_meta.get(
                "snapshot_id"
            )
        ),
    }

    # CRITICAL:
    # no odds["implied"], implied_over, implied_under or ou_line are created
    # from SportyBet. The prediction remains history/base-rate driven.
    context = {
        "competition_type": (
            competition.competition_type
        ),
        "region": competition.region,
        "team_type": competition.team_type,
        "stage": None,
        "round": None,
        "leg_number": None,
        "knockout": False,
        "neutral_venue": False,
        "context_label": (
            competition.display_name
        ),
    }

    fixture = {
        "match_id": (
            f"sportybet-shadow:"
            f"{entry.get('event_id')}"
        ),
        "event_id": None,
        "league_slug": slug,
        "league": competition.display_name,
        "commence_time": kickoff,
        "home": {
            "name": home,
            "logo": None,
            "form": None,
            "record": None,
        },
        "away": {
            "name": away,
            "logo": None,
            "form": None,
            "record": None,
        },
        "venue": {
            "name": None,
            "city": None,
            "country": (
                competition.country
            ),
        },
        "broadcast": [],
        "odds": odds,
        "competition": context,
        "competition_type": (
            competition.competition_type
        ),
        "region": competition.region,
        "team_type": competition.team_type,
        "stage": None,
        "round": None,
        "leg_number": None,
        "knockout": False,
        "neutral_venue": False,
        "context_label": (
            competition.display_name
        ),
        "_sportybet_match": {
            "status": "MATCHED",
            "snapshot_id": (
                board_meta.get(
                    "snapshot_id"
                )
            ),
            "fixture_match_method": (
                "sportybet_native_shadow"
            ),
            "fixture_match_confidence": 1.0,
            "failure_reason": None,
            "league_diagnostic": None,
        },
        "_sportybet_board_meta": dict(
            board_meta
        ),
        "_shadow_supplemental": True,
    }

    return fixture


def _numbers(
    values,
) -> dict:
    parsed = []

    for value in values:
        try:
            value = float(
                value
            )
        except (
            TypeError,
            ValueError,
        ):
            continue

        parsed.append(
            value
        )

    if not parsed:
        return {
            "n": 0,
            "mean": None,
            "median": None,
            "min": None,
            "max": None,
        }

    return {
        "n": len(parsed),
        "mean": round(
            sum(parsed)
            / len(parsed),
            4,
        ),
        "median": round(
            median(parsed),
            4,
        ),
        "min": round(
            min(parsed),
            4,
        ),
        "max": round(
            max(parsed),
            4,
        ),
    }


def _pool_summary(
    picks: list[dict],
) -> dict:
    markets = Counter()
    trust = Counter()

    real = 0
    bookable = 0

    probabilities = []
    quality = []

    for pick in picks:
        markets[
            str(
                pick.get("market")
                or "unknown"
            )
        ] += 1

        trust[
            str(
                pick.get(
                    "market_trust_state"
                )
                or "unknown"
            )
        ] += 1

        real += int(
            bool(
                pick.get(
                    "odds_are_real"
                )
            )
        )

        bookable += int(
            bool(
                pick.get(
                    "bookable"
                )
            )
        )

        probabilities.append(
            pick.get(
                "selection_probability"
            )
            or pick.get(
                "confidence"
            )
        )

        quality.append(
            pick.get(
                "quality_score"
            )
        )

    return {
        "candidate_count": len(
            picks
        ),
        "market_counts": dict(
            markets
        ),
        "trust_state_counts": dict(
            trust
        ),
        "real_price_count": real,
        "bookable_count": bookable,
        "bookable_rate": (
            round(
                bookable
                / len(picks),
                4,
            )
            if picks
            else 0.0
        ),
        "selection_probability": (
            _numbers(
                probabilities
            )
        ),
        "quality_score": (
            _numbers(
                quality
            )
        ),
    }



def _shadow_ratings_for_ready(
    ready: list[dict],
    ratings: dict | None,
) -> tuple[dict, list[str]]:
    """Overlay current ESPN-history Elo for supplemental leagues only.

    The live ratings dictionary is never mutated.
    """
    combined = dict(
        ratings or {}
    )

    slugs = sorted({
        str(
            item.get(
                "league_slug"
            )
            or ""
        )
        for item in ready
        if str(
            item.get(
                "league_slug"
            )
            or ""
        )
    })

    if not slugs:
        return combined, []

    try:
        refreshed = (
            recent_league_ratings(
                slugs,
            )
        )

    except Exception:
        refreshed = {}

    for slug, pool in (
        refreshed or {}
    ).items():
        combined[
            slug
        ] = pool

    return (
        combined,
        sorted(
            refreshed
            or {}
        ),
    )



def evaluate_shadow_supplemental(
    readiness: dict,
    board: dict,
    *,
    cached_rates: dict,
    history,
    ratings: dict,
    fit: dict,
    live_picks: list[dict],
    limit: int = MAX_SHADOW_FIXTURES,
) -> dict:
    """Run real BetSightly logic without adding results to the live pool."""
    original_live_count = len(
        live_picks
    )

    entries = _entry_index(
        board
    )

    meta = _board_meta(
        board
    )

    ready = [
        item
        for item in (
            readiness.get(
                "samples"
            )
            or []
        )
        if (
            item.get(
                "readiness"
            )
            == "READY_FOR_SHADOW_MODEL"
        )
    ][
        :max(
            0,
            int(limit),
        )
    ]

    shadow_ratings, refreshed_elo_leagues = (
        _shadow_ratings_for_ready(
            ready,
            ratings,
        )
    )

    raw_shadow_picks = []

    fixture_results = []

    skipped_context = 0
    elo_count = 0

    for sample in ready:
        event_id = str(
            sample.get(
                "event_id"
            )
            or ""
        )

        entry = entries.get(
            event_id
        )

        if not entry:
            continue

        fixture = _shadow_fixture(
            sample,
            entry,
            meta,
        )

        if fixture is None:
            skipped_context += 1
            continue

        base = rates_for(
            fixture["league_slug"],
            cached_rates,
        )

        fixture[
            "competition_historical_sample"
        ] = int(
            base.get(
                "matches"
            )
            or 0
        )

        fixture[
            "base_rate_source"
        ] = base.get(
            "base_rate_source",
            "competition",
        )

        try:
            elo = probabilities_for_fixture(
                fixture,
                shadow_ratings,
            )

        except Exception:
            elo = None

        if elo:
            elo_count += 1

        model = predict(
            fixture,
            base,
            elo,
        )

        model[
            "elo_probabilities"
        ] = elo

        # No ML vote here yet. The trained ensemble requires independent
        # bookmaker-probability features. Feeding SportyBet into those feature
        # columns would make the same book both input and evaluation price.
        model["ml"] = None

        fixture["_model"] = model

        picks = build_picks(
            fixture,
            model,
            min_confidence=(
                MIN_CANDIDATE_CONFIDENCE
            ),
            fit=fit,
        )

        raw_shadow_picks.extend(
            picks
        )

        fixture_results.append({
            "event_id": event_id,
            "match_id": fixture[
                "match_id"
            ],
            "home_team": (
                fixture["home"]["name"]
            ),
            "away_team": (
                fixture["away"]["name"]
            ),
            "league": fixture[
                "league"
            ],
            "league_slug": fixture[
                "league_slug"
            ],
            "kickoff": fixture[
                "commence_time"
            ],
            "base_rate_source": (
                fixture[
                    "base_rate_source"
                ]
            ),
            "competition_history_matches": (
                fixture[
                    "competition_historical_sample"
                ]
            ),
            "elo_available": bool(
                elo
            ),
            "ml_available": False,
            "candidate_count": len(
                picks
            ),
        })

    shadow_ranked = (
        canonical_fixture_recommendations(
            raw_shadow_picks,
            include_all_eligible=True,
        )
        if raw_shadow_picks
        else []
    )

    # Apply the same ranker to a COPY of the ordinary ESPN pool for a fair
    # descriptive comparison. canonical_fixture_recommendations copies each
    # candidate internally; live_picks itself is never modified.
    live_ranked = (
        canonical_fixture_recommendations(
            live_picks,
            include_all_eligible=True,
        )
        if live_picks
        else []
    )

    shadow_bookable = [
        pick
        for pick in shadow_ranked
        if (
            pick.get(
                "bookable"
            )
            and pick.get(
                "odds_are_real"
            )
            and pick.get(
                "market_floor_eligible",
                True,
            )
        )
    ]

    shadow_summary = _pool_summary(
        shadow_ranked
    )

    live_summary = _pool_summary(
        live_ranked
    )

    from leagues.sportybet_shadow_gate import (
        evaluate_staging_gate,
    )

    staging_gate = evaluate_staging_gate(
        shadow_ranked,
        board_complete=bool(
            meta.get(
                "is_complete"
            )
        ),
        live_summary=live_summary,
        shadow_summary=shadow_summary,
    )

    from leagues.sportybet_shadow_evidence import (
        evaluate_evidence_snapshot_gate,
        staging_builder_merge_candidates,
    )

    settled_evidence_snapshot_gate = (
        evaluate_evidence_snapshot_gate(
            shadow_ranked,
            board_complete=bool(
                meta.get(
                    "is_complete"
                )
            ),
            live_summary=live_summary,
            shadow_summary=shadow_summary,
        )
    )

    (
        staging_builder_candidates,
        staging_builder_merge,
    ) = staging_builder_merge_candidates(
        shadow_ranked,
        board_complete=bool(
            meta.get(
                "is_complete"
            )
        ),
    )

    from leagues.sportybet_shadow_gate import (
        production_bridge_candidates,
    )

    (
        production_candidates,
        production_bridge,
    ) = production_bridge_candidates(
        shadow_ranked,
        board_complete=bool(
            meta.get(
                "is_complete"
            )
        ),
    )

    fixture_results.sort(
        key=lambda item: (
            item.get("kickoff")
            or "",
            item.get("event_id")
            or "",
        )
    )

    samples = []

    for pick in shadow_ranked[:20]:
        fixture = (
            pick.get(
                "_fixture"
            )
            or {}
        )

        samples.append({
            "match_id": pick.get(
                "match_id"
            ),
            "home_team": (
                (
                    fixture.get("home")
                    or {}
                ).get("name")
            ),
            "away_team": (
                (
                    fixture.get("away")
                    or {}
                ).get("name")
            ),
            "league": fixture.get(
                "league"
            ),
            "market": pick.get(
                "market"
            ),
            "confidence": pick.get(
                "confidence"
            ),
            "selection_probability": (
                pick.get(
                    "selection_probability"
                )
            ),
            "quality_score": pick.get(
                "quality_score"
            ),
            "market_trust_state": (
                pick.get(
                    "market_trust_state"
                )
            ),
            "market_floor_eligible": bool(
                pick.get(
                    "market_floor_eligible"
                )
            ),
            "safe_tier_eligible": bool(
                pick.get(
                    "safe_tier_eligible"
                )
            ),
            "lower_reliability_bound": (
                pick.get(
                    "lower_reliability_bound"
                )
            ),
            "evidence_strength": (
                pick.get(
                    "evidence_strength"
                )
            ),
            "odds": pick.get(
                "odds"
            ),
            "odds_are_real": bool(
                pick.get(
                    "odds_are_real"
                )
            ),
            "bookable": bool(
                pick.get(
                    "bookable"
                )
            ),
            "base_rate_source": (
                fixture.get(
                    "base_rate_source"
                )
            ),
            "elo_available": bool(
                (
                    pick.get(
                        "_model"
                    )
                    or {}
                ).get(
                    "elo_probabilities"
                )
            ),
            "ml_available": bool(
                (
                    pick.get(
                        "_model"
                    )
                    or {}
                ).get(
                    "ml"
                )
            ),
        })

    return {
        "status": "success",
        "shadow_only": True,
        "read_only": True,
        "publishing_changed": False,
        "prediction_pool_changed": False,
        "official_record_changed": False,
        "booking_exposed": False,
        "sportybet_used_as_probability_anchor": False,
        "sportybet_used_as_price_source": True,
        "sportybet_board_complete": bool(
            meta.get(
                "is_complete"
            )
        ),
        "staging_gate": staging_gate,
        "settled_evidence_snapshot_gate": (
            settled_evidence_snapshot_gate
        ),
        "staging_builder_merge": (
            staging_builder_merge
        ),
        "_staging_builder_candidates": (
            staging_builder_candidates
        ),
        "production_bridge": (
            production_bridge
        ),
        "_production_candidates": (
            production_candidates
        ),
        "ready_input_fixture_count": len(
            ready
        ),
        "modelled_fixture_count": len(
            fixture_results
        ),
        "skipped_context_fixture_count": (
            skipped_context
        ),
        "elo_fixture_count": elo_count,
        "elo_source": (
            "espn_monthly_history_shadow_only"
        ),
        "elo_refreshed_league_count": len(
            refreshed_elo_leagues
        ),
        "elo_refreshed_leagues": (
            refreshed_elo_leagues
        ),
        "ml_fixture_count": 0,
        "raw_shadow_candidate_count": len(
            raw_shadow_picks
        ),
        "ranked_shadow_candidate_count": len(
            shadow_ranked
        ),
        "bookable_shadow_candidate_count": len(
            shadow_bookable
        ),
        "shadow_pool": shadow_summary,
        "live_espn_pool": live_summary,
        "fixture_samples": fixture_results[
            :20
        ],
        "candidate_samples": samples,
        "live_pick_count_before": (
            original_live_count
        ),
        "live_pick_count_after": len(
            live_picks
        ),
        "next_gate": (
            (
                "staging Builder merge is active; next gate is Builder stress, "
                "isolation, and reliability validation before any production promotion"
            )
            if (
                staging_builder_merge
                and staging_builder_merge.get("merge_executed")
            )
            else (
                "shadow supplemental candidates must show comparable evidence/"
                "quality characteristics before any feature-flagged staging Builder merge"
            )
        ),
    }
