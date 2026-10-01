"""Combined Phase 8B.3-8B.6 runtime-context experiment.

Additive only. Nothing here is wired into the deployed predictor.
"""

from __future__ import annotations

from collections import Counter, defaultdict, deque

import numpy as np
import pandas as pd

from leagues.base_rates import (
    GLOBAL_DEFAULTS,
    LOOKBACK_DAYS as BASE_LOOKBACK_DAYS,
    _as_rates,
    _empty,
    _merge,
    rates_for,
)
from leagues.competition_registry import competition_for
from leagues.football_first_challenger import TARGET_COLUMNS
from leagues.football_first_runtime_core import (
    RUNTIME_FEATURE_COLUMNS,
    normalize_runtime_core_frame,
)
from leagues.football_first_runtime_elo import (
    API_LEAGUE_TO_ESPN_SLUG,
    RUNTIME_ELO_FEATURE_COLUMNS,
)
from leagues.football_first_stability import (
    _evaluate_target_fold,
    temporal_folds,
)
from leagues.team_history import (
    LOOKBACK_DAYS as TEAM_LOOKBACK_DAYS,
    NEUTRAL,
)


RUNTIME_V2_VERSION = "football-first-runtime-v2-context-v1"


LEAGUE_TO_SLUG = {
    **API_LEAGUE_TO_ESPN_SLUG,
    1: "fifa.world",
    2: "uefa.champions",
    3: "uefa.europa",
    11: "conmebol.sudamericana",
    13: "conmebol.libertadores",
    848: "uefa.europa.conf",
}


BASE_COLUMNS = [
    "runtime_base_sample_scaled",
    "runtime_base_home_win",
    "runtime_base_draw",
    "runtime_base_away_win",
    "runtime_base_over_1_5",
    "runtime_base_over_2_5",
    "runtime_base_btts",
    "runtime_base_home_goals",
    "runtime_base_away_goals",
]

VENUE_COLUMNS = [
    "runtime_home_venue_win_5",
    "runtime_home_venue_goals_5",
    "runtime_away_venue_win_5",
    "runtime_away_venue_goals_5",
]

REST_COLUMNS = [
    "runtime_home_rest_available",
    "runtime_home_rest_days_scaled",
    "runtime_home_short_rest",
    "runtime_away_rest_available",
    "runtime_away_rest_days_scaled",
    "runtime_away_short_rest",
]

CONTEXT_COLUMNS = [
    *BASE_COLUMNS,
    *VENUE_COLUMNS,
    *REST_COLUMNS,
]

# Phase 8B.6 selected candidate.
# Rest was evaluated but excluded because the 32-feature
# Elo + base-rate + venue candidate performed better overall.
V2_CANDIDATE_VERSION = "football-first-runtime-v2-candidate-32-v1"

V2_CANDIDATE_FEATURE_COLUMNS = [
    *RUNTIME_FEATURE_COLUMNS,
    *RUNTIME_ELO_FEATURE_COLUMNS,
    *BASE_COLUMNS,
    *VENUE_COLUMNS,
]


def _sample_delta(
    sample: dict,
    hs: int,
    aws: int,
    sign: int,
) -> None:
    total = hs + aws

    sample["n"] += sign
    sample["goals"] += sign * total
    sample["home_goals"] += sign * hs
    sample["away_goals"] += sign * aws

    sample["o15"] += sign * int(
        total >= 2
    )
    sample["o25"] += sign * int(
        total >= 3
    )
    sample["home"] += sign * int(
        hs > aws
    )
    sample["draw"] += sign * int(
        hs == aws
    )
    sample["away"] += sign * int(
        hs < aws
    )
    sample["btts"] += sign * int(
        hs >= 1 and aws >= 1
    )


def _cached_rates(
    samples: dict[str, dict],
) -> dict:
    cached = {}
    priors = defaultdict(_empty)

    for slug, sample in samples.items():
        if int(sample.get("n") or 0) <= 0:
            continue

        cached[slug] = _as_rates(sample)

        meta = competition_for(slug)

        if meta is None:
            continue

        keys = (
            f"region_type:{meta.region}|"
            f"{meta.competition_type}",
            f"competition_type:"
            f"{meta.competition_type}",
            f"team_type:{meta.team_type}",
            "global",
        )

        for key in keys:
            _merge(
                priors[key],
                sample,
            )

    cached["_priors"] = {
        key: _as_rates(sample)
        for key, sample in priors.items()
        if int(sample.get("n") or 0) > 0
    }

    return cached


def _base_values(
    slug: str,
    cached: dict,
) -> dict:
    base = rates_for(
        slug,
        cached,
    )

    n = int(
        base.get("matches")
        or 0
    )

    return {
        "runtime_base_sample_scaled":
            min(n, 45) / 45.0,

        "runtime_base_home_win":
            float(
                base.get(
                    "home_win",
                    GLOBAL_DEFAULTS["home_win"],
                )
            ),

        "runtime_base_draw":
            float(
                base.get(
                    "draw",
                    GLOBAL_DEFAULTS["draw"],
                )
            ),

        "runtime_base_away_win":
            float(
                base.get(
                    "away_win",
                    GLOBAL_DEFAULTS["away_win"],
                )
            ),

        "runtime_base_over_1_5":
            float(
                base.get(
                    "over_1_5",
                    GLOBAL_DEFAULTS["over_1_5"],
                )
            ),

        "runtime_base_over_2_5":
            float(
                base.get(
                    "over_2_5",
                    GLOBAL_DEFAULTS["over_2_5"],
                )
            ),

        "runtime_base_btts":
            float(
                base.get(
                    "btts",
                    GLOBAL_DEFAULTS["btts"],
                )
            ),

        "runtime_base_home_goals":
            float(
                base.get(
                    "home_goals",
                    GLOBAL_DEFAULTS["home_goals"],
                )
            ),

        "runtime_base_away_goals":
            float(
                base.get(
                    "away_goals",
                    GLOBAL_DEFAULTS["away_goals"],
                )
            ),
    }


def _venue_values(
    rows: deque,
    venue: str,
) -> tuple[float, float]:
    picked = [
        row
        for row in reversed(rows)
        if row["venue"] == venue
    ][:5]

    if not picked:
        return (
            float(
                NEUTRAL["venue_win_rate_5"]
            ),
            float(
                NEUTRAL["venue_goals_5"]
            ),
        )

    wins = sum(
        row["gf"] > row["ga"]
        for row in picked
    )

    goals = sum(
        row["gf"]
        for row in picked
    )

    return (
        wins / len(picked),
        goals / len(picked),
    )


def _utc_calendar_day(
    value,
) -> pd.Timestamp:
    """Normalize aware/naive inputs to one UTC-naive calendar day.

    Live HistoryIndex rows can contain naive timestamps while provider
    fixture kickoff values are timezone-aware.  Converting aware values to
    UTC before dropping timezone information makes the comparison
    deterministic and avoids mixing tz-aware and tz-naive timestamps.
    """

    timestamp = pd.Timestamp(
        value
    )

    if pd.isna(
        timestamp
    ):
        raise ValueError(
            "invalid_rest_timestamp"
        )

    if (
        timestamp.tzinfo
        is not None
    ):
        timestamp = (
            timestamp
            .tz_convert(
                "UTC"
            )
            .tz_localize(
                None
            )
        )

    return timestamp.normalize()


def rest_snapshot(
    current_day,
    prior_days,
) -> dict:
    """Shared V2 rest contract.

    Uses UTC calendar days so offline and future runtime
    inference can reproduce exactly the same feature.
    """

    current = _utc_calendar_day(
        current_day
    )

    previous = []

    for value in prior_days:
        prior = _utc_calendar_day(
            value
        )

        if prior < current:
            previous.append(
                prior
            )

    if not previous:
        return {
            "available": 0.0,
            "days_scaled": 7.0 / 30.0,
            "short_rest": 0.0,
        }

    days = int(
        (
            current
            - max(previous)
        ).days
    )

    days = max(
        0,
        min(
            30,
            days,
        ),
    )

    return {
        "available": 1.0,
        "days_scaled":
            days / 30.0,
        "short_rest":
            1.0 if days < 4 else 0.0,
    }



def runtime_candidate_context_vector(
    fixture: dict,
    index,
    cached_rates: dict,
) -> dict:
    """Build only the context actually used by the frozen 32-feature V2.

    The selected candidate uses base-rate and venue features but explicitly
    excludes rest.  Rest therefore must not become a runtime dependency for
    prospective V2 observations.
    """

    slug = str(
        fixture.get(
            "league_slug"
        )
        or ""
    )

    team_type = str(
        fixture.get(
            "team_type"
        )
        or "CLUB"
    )

    home = str(
        (
            fixture.get("home")
            or {}
        ).get("name")
        or ""
    )

    away = str(
        (
            fixture.get("away")
            or {}
        ).get("name")
        or ""
    )

    values = _base_values(
        slug,
        cached_rates,
    )

    home_form = index.team_form(
        home,
        "home",
        team_type,
    )

    away_form = index.team_form(
        away,
        "away",
        team_type,
    )

    values.update({
        "runtime_home_venue_win_5":
            float(
                home_form[
                    "venue_win_rate_5"
                ]
            ),

        "runtime_home_venue_goals_5":
            float(
                home_form[
                    "venue_goals_5"
                ]
            ),

        "runtime_away_venue_win_5":
            float(
                away_form[
                    "venue_win_rate_5"
                ]
            ),

        "runtime_away_venue_goals_5":
            float(
                away_form[
                    "venue_goals_5"
                ]
            ),
    })

    candidate_columns = [
        *BASE_COLUMNS,
        *VENUE_COLUMNS,
    ]

    return {
        "status":
            "READY",

        "feature_version":
            V2_CANDIDATE_VERSION,

        "features":
            values,

        "vector": [
            float(
                values[
                    column
                ]
            )
            for column
            in candidate_columns
        ],
    }

def runtime_context_vector(
    fixture: dict,
    index,
    cached_rates: dict,
) -> dict:
    """Future-runtime V2 context builder."""

    slug = str(
        fixture.get(
            "league_slug"
        )
        or ""
    )

    team_type = str(
        fixture.get(
            "team_type"
        )
        or "CLUB"
    )

    home = str(
        (
            fixture.get("home")
            or {}
        ).get("name")
        or ""
    )

    away = str(
        (
            fixture.get("away")
            or {}
        ).get("name")
        or ""
    )

    day = pd.Timestamp(
        fixture.get(
            "commence_time"
        )
        or fixture.get(
            "kickoff"
        )
        or fixture.get(
            "date"
        )
    ).normalize()

    values = _base_values(
        slug,
        cached_rates,
    )

    home_form = index.team_form(
        home,
        "home",
        team_type,
    )

    away_form = index.team_form(
        away,
        "away",
        team_type,
    )

    values.update({
        "runtime_home_venue_win_5":
            float(
                home_form[
                    "venue_win_rate_5"
                ]
            ),

        "runtime_home_venue_goals_5":
            float(
                home_form[
                    "venue_goals_5"
                ]
            ),

        "runtime_away_venue_win_5":
            float(
                away_form[
                    "venue_win_rate_5"
                ]
            ),

        "runtime_away_venue_goals_5":
            float(
                away_form[
                    "venue_goals_5"
                ]
            ),
    })

    home_rest = rest_snapshot(
        day,
        [
            row["date"]
            for row in index.by_team.get(
                (
                    team_type,
                    home,
                ),
                [],
            )
        ],
    )

    away_rest = rest_snapshot(
        day,
        [
            row["date"]
            for row in index.by_team.get(
                (
                    team_type,
                    away,
                ),
                [],
            )
        ],
    )

    values.update({
        "runtime_home_rest_available":
            home_rest["available"],

        "runtime_home_rest_days_scaled":
            home_rest["days_scaled"],

        "runtime_home_short_rest":
            home_rest["short_rest"],

        "runtime_away_rest_available":
            away_rest["available"],

        "runtime_away_rest_days_scaled":
            away_rest["days_scaled"],

        "runtime_away_short_rest":
            away_rest["short_rest"],
    })

    return {
        "status": "READY",
        "feature_version":
            RUNTIME_V2_VERSION,
        "features": values,
        "vector": [
            float(
                values[column]
            )
            for column
            in CONTEXT_COLUMNS
        ],
    }


def attach_historical_context(
    combined_results: pd.DataFrame,
    runtime_features: pd.DataFrame,
) -> tuple[pd.DataFrame, dict]:

    frame = runtime_features.copy()

    for column in CONTEXT_COLUMNS:
        frame[column] = 0.0

    if frame.empty:
        return frame, {
            "feature_version":
                RUNTIME_V2_VERSION,
            "samples": 0,
        }

    source = combined_results.copy()

    source["date"] = (
        pd.to_datetime(
            source["date"],
            errors="coerce",
        )
        .dt.normalize()
    )

    source = (
        source
        .dropna(
            subset=[
                "date",
                "league_id",
                "home_team",
                "away_team",
                "home_score",
                "away_score",
            ]
        )
        .sort_values(
            [
                "date",
                "league_id",
                "home_team",
                "away_team",
            ]
        )
    )

    source["league_id"] = (
        source["league_id"]
        .astype(int)
    )

    frame["date"] = (
        pd.to_datetime(
            frame["date"],
            errors="raise",
        )
        .dt.normalize()
    )

    frame["league_id"] = (
        frame["league_id"]
        .astype(int)
    )

    source_by_day = defaultdict(list)

    for row in source.to_dict(
        "records"
    ):
        source_by_day[
            pd.Timestamp(
                row["date"]
            )
        ].append(row)

    targets_by_day = {
        pd.Timestamp(day):
            list(group.index)
        for day, group
        in frame.groupby(
            "date",
            sort=True,
        )
    }

    league_samples = defaultdict(
        _empty
    )

    base_window = deque()

    team_history = defaultdict(
        deque
    )

    base_available = 0
    home_venue_available = 0
    away_venue_available = 0
    home_rest_available = 0
    away_rest_available = 0

    all_days = sorted(
        set(source_by_day)
        | set(targets_by_day)
    )

    for day in all_days:

        base_cutoff = (
            day
            - pd.Timedelta(
                days=BASE_LOOKBACK_DAYS
            )
        )

        while (
            base_window
            and base_window[0]["day"]
            < base_cutoff
        ):
            old = base_window.popleft()

            _sample_delta(
                league_samples[
                    old["slug"]
                ],
                old["hs"],
                old["aws"],
                -1,
            )

        if day in targets_by_day:

            cached = _cached_rates(
                league_samples
            )

            team_cutoff = (
                day
                - pd.Timedelta(
                    days=TEAM_LOOKBACK_DAYS
                )
            )

            for index in targets_by_day[
                day
            ]:

                league_id = int(
                    frame.at[
                        index,
                        "league_id",
                    ]
                )

                slug = LEAGUE_TO_SLUG.get(
                    league_id,
                    "",
                )

                base = _base_values(
                    slug,
                    cached,
                )

                for column, value in base.items():
                    frame.at[
                        index,
                        column,
                    ] = value

                if (
                    base[
                        "runtime_base_sample_scaled"
                    ]
                    > 0
                ):
                    base_available += 1

                team_type = str(
                    frame.at[
                        index,
                        "team_type",
                    ]
                    or "CLUB"
                )

                for side, venue in (
                    (
                        "home",
                        "home",
                    ),
                    (
                        "away",
                        "away",
                    ),
                ):

                    team = str(
                        frame.at[
                            index,
                            f"{side}_team",
                        ]
                    )

                    history = (
                        team_history[
                            (
                                team_type,
                                team,
                            )
                        ]
                    )

                    while (
                        history
                        and history[0]["day"]
                        < team_cutoff
                    ):
                        history.popleft()

                    venue_win, venue_goals = (
                        _venue_values(
                            history,
                            venue,
                        )
                    )

                    frame.at[
                        index,
                        f"runtime_{side}_venue_win_5",
                    ] = venue_win

                    frame.at[
                        index,
                        f"runtime_{side}_venue_goals_5",
                    ] = venue_goals

                    if any(
                        row["venue"]
                        == venue
                        for row
                        in history
                    ):
                        if side == "home":
                            home_venue_available += 1
                        else:
                            away_venue_available += 1

                    rest = rest_snapshot(
                        day,
                        [
                            row["day"]
                            for row
                            in history
                        ],
                    )

                    frame.at[
                        index,
                        f"runtime_{side}_rest_available",
                    ] = rest[
                        "available"
                    ]

                    frame.at[
                        index,
                        f"runtime_{side}_rest_days_scaled",
                    ] = rest[
                        "days_scaled"
                    ]

                    frame.at[
                        index,
                        f"runtime_{side}_short_rest",
                    ] = rest[
                        "short_rest"
                    ]

                    if rest["available"]:
                        if side == "home":
                            home_rest_available += 1
                        else:
                            away_rest_available += 1

        # Same-day results are inserted only after
        # all pre-match features for the date are built.
        for row in source_by_day.get(
            day,
            [],
        ):

            slug = LEAGUE_TO_SLUG.get(
                int(
                    row["league_id"]
                )
            )

            if (
                slug
                and competition_for(
                    slug
                )
                is not None
            ):
                item = {
                    "day": day,
                    "slug": slug,
                    "hs": int(
                        row[
                            "home_score"
                        ]
                    ),
                    "aws": int(
                        row[
                            "away_score"
                        ]
                    ),
                }

                base_window.append(
                    item
                )

                _sample_delta(
                    league_samples[
                        slug
                    ],
                    item["hs"],
                    item["aws"],
                    1,
                )

            team_type = str(
                row.get(
                    "team_type"
                )
                or "CLUB"
            )

            team_history[
                (
                    team_type,
                    str(
                        row[
                            "home_team"
                        ]
                    ),
                )
            ].append({
                "day": day,
                "venue": "home",
                "gf": int(
                    row[
                        "home_score"
                    ]
                ),
                "ga": int(
                    row[
                        "away_score"
                    ]
                ),
            })

            team_history[
                (
                    team_type,
                    str(
                        row[
                            "away_team"
                        ]
                    ),
                )
            ].append({
                "day": day,
                "venue": "away",
                "gf": int(
                    row[
                        "away_score"
                    ]
                ),
                "ga": int(
                    row[
                        "home_score"
                    ]
                ),
            })

    samples = len(frame)

    return frame, {
        "feature_version":
            RUNTIME_V2_VERSION,

        "samples":
            samples,

        "same_day_results_visible":
            False,

        "base_rate_lookback_days":
            BASE_LOOKBACK_DAYS,

        "team_history_lookback_days":
            TEAM_LOOKBACK_DAYS,

        "base_available":
            base_available,

        "base_availability_rate":
            round(
                base_available
                / samples,
                6,
            ),

        "home_venue_available":
            home_venue_available,

        "away_venue_available":
            away_venue_available,

        "home_rest_available":
            home_rest_available,

        "away_rest_available":
            away_rest_available,

        "base_rate_formula_matches_live_rates_for":
            True,

        # Historical corpus does not contain every
        # league tracked by the live ESPN registry.
        "base_rate_prior_universe_complete":
            False,

        "base_rate_prior_blocker":
            (
                "historical corpus does not contain "
                "every competition in the live ESPN registry"
            ),

        "venue_formula_matches_history_index":
            True,

        "rest_contract":
            "shared_calendar_day_v2",

        "rest_contract_matches_old_runtime_rest_context":
            False,

        "automatic_promotion":
            False,
    }


def _summary(
    rows: list[dict],
) -> dict:

    skills = [
        float(
            row[
                "log_loss_skill_vs_prior"
            ]
        )
        for row in rows
    ]

    return {
        "fold_count":
            len(rows),

        "positive_skill_folds":
            sum(
                value > 0
                for value in skills
            ),

        "median_skill":
            (
                round(
                    float(
                        np.median(
                            skills
                        )
                    ),
                    6,
                )
                if skills
                else None
            ),

        "minimum_skill":
            (
                round(
                    float(
                        min(
                            skills
                        )
                    ),
                    6,
                )
                if skills
                else None
            ),

        "family_selection_counts":
            dict(
                Counter(
                    row[
                        "selected_family"
                    ]
                    for row in rows
                )
            ),
    }


def evaluate_runtime_v2(
    features: pd.DataFrame,
    *,
    n_folds: int = 4,
) -> dict:

    frame = (
        normalize_runtime_core_frame(
            features
        )
    )

    required = [
        *RUNTIME_ELO_FEATURE_COLUMNS,
        *CONTEXT_COLUMNS,
    ]

    missing = [
        column
        for column in required
        if column not in frame.columns
    ]

    if missing:
        raise ValueError(
            "Missing runtime V2 features: "
            + ", ".join(
                missing
            )
        )

    variants = {
        "runtime_core_v1":
            list(
                RUNTIME_FEATURE_COLUMNS
            ),

        "runtime_core_plus_elo": [
            *RUNTIME_FEATURE_COLUMNS,
            *RUNTIME_ELO_FEATURE_COLUMNS,
        ],

        "runtime_core_plus_elo_base": [
            *RUNTIME_FEATURE_COLUMNS,
            *RUNTIME_ELO_FEATURE_COLUMNS,
            *BASE_COLUMNS,
        ],

        "runtime_core_plus_elo_base_venue":
            list(
                V2_CANDIDATE_FEATURE_COLUMNS
            ),

        "runtime_v2_full": [
            *RUNTIME_FEATURE_COLUMNS,
            *RUNTIME_ELO_FEATURE_COLUMNS,
            *BASE_COLUMNS,
            *VENUE_COLUMNS,
            *REST_COLUMNS,
        ],
    }

    folds = temporal_folds(
        frame,
        n_folds=n_folds,
    )

    matrices = {
        name:
            frame[
                columns
            ].astype(
                float
            ).to_numpy()
        for name, columns
        in variants.items()
    }

    targets = {}

    for (
        target,
        target_column,
    ) in TARGET_COLUMNS.items():

        y = frame[
            target_column
        ].to_numpy()

        result_by_variant = {}

        for (
            name,
            columns,
        ) in variants.items():

            fold_rows = []

            for fold in folds:

                result = (
                    _evaluate_target_fold(
                        matrices[
                            name
                        ],
                        y,
                        fold,
                    )
                )

                if result is None:
                    continue

                fold_rows.append({
                    "fold":
                        int(
                            fold[
                                "fold"
                            ]
                        ),

                    "test_start":
                        fold[
                            "test_start"
                        ],

                    "test_end":
                        fold[
                            "test_end"
                        ],

                    "test_n":
                        len(
                            fold[
                                "test_indices"
                            ]
                        ),

                    "selected_family":
                        result[
                            "selected_family"
                        ],

                    "log_loss_skill_vs_prior":
                        result[
                            "log_loss_skill_vs_prior"
                        ],

                    "test":
                        result[
                            "test"
                        ],
                })

            result_by_variant[
                name
            ] = {
                **_summary(
                    fold_rows
                ),
                "feature_count":
                    len(
                        columns
                    ),
                "folds":
                    fold_rows,
            }

        core = (
            result_by_variant[
                "runtime_core_v1"
            ][
                "median_skill"
            ]
        )

        previous = None

        for name in variants:
            current = (
                result_by_variant[
                    name
                ][
                    "median_skill"
                ]
            )

            result_by_variant[
                name
            ][
                "delta_vs_core"
            ] = (
                round(
                    float(
                        current
                        - core
                    ),
                    6,
                )
                if (
                    current is not None
                    and core is not None
                )
                else None
            )

            result_by_variant[
                name
            ][
                "delta_vs_previous"
            ] = (
                round(
                    float(
                        current
                        - previous
                    ),
                    6,
                )
                if (
                    current is not None
                    and previous is not None
                )
                else None
            )

            previous = current

        targets[
            target
        ] = result_by_variant

    match_result = (
        targets[
            "match_result"
        ][
            "runtime_v2_full"
        ]
    )

    return {
        "schema": 1,

        "experiment":
            "football_first_runtime_v2_combined_v1",

        "feature_version":
            RUNTIME_V2_VERSION,

        "variants": {
            name: {
                "feature_count":
                    len(
                        columns
                    ),
                "feature_columns":
                    columns,
            }
            for name, columns
            in variants.items()
        },

        "targets":
            targets,

        "match_result_signal_positive":
            bool(
                match_result[
                    "median_skill"
                ]
                is not None
                and match_result[
                    "median_skill"
                ]
                > 0
                and match_result[
                    "positive_skill_folds"
                ]
                >= 3
            ),

        "runtime_artifact_ready":
            False,

        "runtime_artifact_blockers": [
            "historical_base_rate_prior_universe_incomplete",
            "historical_tournament_neutral_context_not_available",
            "korea_saudi_historical_coverage_missing",
            "prospective_v1_shadow_evidence_is_still_collecting",
        ],

        "automatic_promotion":
            False,

        "live_adjustment_allowed":
            False,
    }
