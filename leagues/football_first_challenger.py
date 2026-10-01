# Offline football-first challenger dataset and evaluation.
#
# This module is deliberately isolated from the deployed 25-feature
# market-price ensemble. It uses only pre-match football information:
# rolling form, venue form, H2H, competition base rates, rest and Elo.

from __future__ import annotations

import math
from collections import Counter, defaultdict, deque
from pathlib import Path

import numpy as np
import pandas as pd

from leagues.canonical_identity import normalize_team
from leagues.chronological_split import describe_whole_date_split

FORM_WINDOW = 5
H2H_WINDOW = 10
LEAGUE_WINDOW = 200
ELO_DEFAULT = 1500.0
ELO_HOME_ADVANTAGE = 75.0
ELO_K = 20.0

FEATURE_COLUMNS = [
    "home_win_rate_5",
    "home_win_rate_10",
    "home_draw_rate_5",
    "home_goals_scored_5",
    "home_goals_conceded_5",
    "home_home_win_rate_5",
    "home_home_goals_5",
    "away_win_rate_5",
    "away_win_rate_10",
    "away_draw_rate_5",
    "away_goals_scored_5",
    "away_goals_conceded_5",
    "away_away_win_rate_5",
    "away_away_goals_5",
    "h2h_home_win_rate",
    "h2h_avg_goals",
    "h2h_btts_rate",
    "h2h_meetings",
    "competition_home_goals",
    "competition_away_goals",
    "competition_over_1_5_rate",
    "competition_over_2_5_rate",
    "competition_btts_rate",
    "elo_home_expectation",
    "elo_diff_scaled",
    "home_rest_days_scaled",
    "away_rest_days_scaled",
    "national_team_match",
]

TARGET_COLUMNS = {
    "match_result": "target_match_result",
    "over_1_5": "target_over_1_5",
    "over_2_5": "target_over_2_5",
    "btts": "target_btts",
}


def _clean(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value).strip()


def _int(value) -> int | None:
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _team_type(league_id: int | None) -> str:
    return "NATIONAL" if league_id == 1 else "CLUB"


def team_identity(name: str, league_id: int | None) -> str:
    return f"{_team_type(league_id)}:{normalize_team(name or '')}"


def fixture_identity(row: dict) -> tuple:
    league_id = _int(row.get("league_id"))
    return (
        str(row.get("date") or "")[:10],
        league_id,
        team_identity(_clean(row.get("home_team")), league_id),
        team_identity(_clean(row.get("away_team")), league_id),
    )


def _normalized_result_row(
    raw: dict,
    *,
    source_dataset: str,
    source_class: str,
) -> dict | None:
    date_value = pd.to_datetime(raw.get("date"), errors="coerce")
    home = _clean(raw.get("home_team"))
    away = _clean(raw.get("away_team"))
    home_score = _int(raw.get("home_score"))
    away_score = _int(raw.get("away_score"))
    league_id = _int(raw.get("league_id"))

    if (
        pd.isna(date_value)
        or not home
        or not away
        or home_score is None
        or away_score is None
        or league_id is None
    ):
        return None

    competition = (
        _clean(raw.get("league_name"))
        or _clean(raw.get("competition"))
        or f"league-{league_id}"
    )

    return {
        "date": pd.Timestamp(date_value).date().isoformat(),
        "league_id": league_id,
        "competition": competition,
        "home_team": home,
        "away_team": away,
        "home_score": home_score,
        "away_score": away_score,
        "source_dataset": source_dataset,
        "source_class": source_class,
        "team_type": _team_type(league_id),
    }


def combine_results(
    legacy: pd.DataFrame,
    football_history: pd.DataFrame,
) -> tuple[pd.DataFrame, dict]:
    normalized: list[dict] = []

    for raw in legacy.to_dict("records"):
        row = _normalized_result_row(
            raw,
            source_dataset="legacy_training_baseline",
            source_class="LEGACY_MARKET_CORPUS_RESULTS_VIEW",
        )
        if row is not None:
            normalized.append(row)

    for raw in football_history.to_dict("records"):
        row = _normalized_result_row(
            raw,
            source_dataset="football_history",
            source_class="RESULTS_ONLY",
        )
        if row is not None:
            normalized.append(row)

    by_identity: dict[tuple, dict] = {}
    duplicate_rows = 0
    same_score_duplicates = 0

    for row in normalized:
        key = fixture_identity(row)
        prior = by_identity.get(key)
        if prior is None:
            by_identity[key] = row
            continue

        duplicate_rows += 1
        prior_score = (prior["home_score"], prior["away_score"])
        score = (row["home_score"], row["away_score"])
        if prior_score != score:
            raise ValueError(
                f"Conflicting fixture result for {key}: "
                f"{prior_score} vs {score}"
            )

        same_score_duplicates += 1
        if (
            prior["source_dataset"] != "football_history"
            and row["source_dataset"] == "football_history"
        ):
            by_identity[key] = row

    frame = pd.DataFrame(
        sorted(
            by_identity.values(),
            key=lambda row: (
                row["date"],
                row["league_id"],
                row["home_team"],
                row["away_team"],
            ),
        )
    )

    stats = {
        "input_normalized_rows": len(normalized),
        "unique_rows": len(frame),
        "duplicate_rows": duplicate_rows,
        "same_score_duplicates_removed": same_score_duplicates,
        "conflicting_duplicates": 0,
        "source_counts": dict(
            Counter(frame["source_dataset"].tolist())
            if not frame.empty else {}
        ),
        "league_count": int(frame["league_id"].nunique()) if not frame.empty else 0,
        "min_date": str(frame["date"].min()) if not frame.empty else None,
        "max_date": str(frame["date"].max()) if not frame.empty else None,
    }
    return frame, stats


def load_combined_results(
    *,
    legacy_csv: Path,
    football_history_csv: Path,
) -> tuple[pd.DataFrame, dict]:
    legacy = pd.read_csv(legacy_csv, low_memory=False)
    history = pd.read_csv(football_history_csv, low_memory=False)
    return combine_results(legacy, history)


def _stats(games) -> dict:
    values = list(games)
    if not values:
        return {
            "win_rate": 0.5,
            "draw_rate": 0.25,
            "goals_scored": 1.2,
            "goals_conceded": 1.2,
        }

    wins = draws = scored = conceded = 0.0
    for goals_for, goals_against in values:
        scored += goals_for
        conceded += goals_against
        if goals_for > goals_against:
            wins += 1
        elif goals_for == goals_against:
            draws += 1

    n = len(values)
    return {
        "win_rate": wins / n,
        "draw_rate": draws / n,
        "goals_scored": scored / n,
        "goals_conceded": conceded / n,
    }


def _league_rates(games) -> tuple[float, float, float, float, float]:
    values = list(games)
    if not values:
        return (1.45, 1.15, 0.75, 0.52, 0.50)

    n = len(values)
    home_goals = sum(h for h, _ in values) / n
    away_goals = sum(a for _, a in values) / n
    over15 = sum((h + a) > 1 for h, a in values) / n
    over25 = sum((h + a) > 2 for h, a in values) / n
    btts = sum(h > 0 and a > 0 for h, a in values) / n
    return home_goals, away_goals, over15, over25, btts


def _rest_days(current: pd.Timestamp, previous: pd.Timestamp | None) -> float:
    if previous is None:
        return 7.0 / 30.0
    days = max(0, min(30, int((current.normalize() - previous.normalize()).days)))
    return days / 30.0


def _elo_expectation(home_rating: float, away_rating: float) -> float:
    diff = home_rating + ELO_HOME_ADVANTAGE - away_rating
    return 1.0 / (1.0 + 10.0 ** (-diff / 400.0))


def build_feature_frame(
    matches: pd.DataFrame,
) -> tuple[pd.DataFrame, dict]:
    if matches.empty:
        return pd.DataFrame(), {
            "input_matches": 0,
            "trainable_samples": 0,
            "warmup_skipped": 0,
        }

    frame = matches.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame = frame.dropna(
        subset=[
            "date",
            "home_team",
            "away_team",
            "home_score",
            "away_score",
            "league_id",
        ]
    )
    frame = frame.sort_values(
        ["date", "league_id", "home_team", "away_team"]
    ).reset_index(drop=True)

    team_games = defaultdict(lambda: deque(maxlen=20))
    home_games = defaultdict(lambda: deque(maxlen=20))
    away_games = defaultdict(lambda: deque(maxlen=20))
    h2h_games = defaultdict(lambda: deque(maxlen=H2H_WINDOW))
    league_games = defaultdict(lambda: deque(maxlen=LEAGUE_WINDOW))
    team_count = defaultdict(int)
    elo = defaultdict(lambda: ELO_DEFAULT)
    last_played: dict[str, pd.Timestamp] = {}

    output: list[dict] = []
    warmup_skipped = 0
    rows = frame.to_dict("records")
    i = 0

    while i < len(rows):
        day = pd.Timestamp(rows[i]["date"]).normalize()
        j = i
        day_rows = []
        while (
            j < len(rows)
            and pd.Timestamp(rows[j]["date"]).normalize() == day
        ):
            day_rows.append(rows[j])
            j += 1

        # Compute all pre-match features first. Same-date results are unseen.
        for row in day_rows:
            league_id = int(row["league_id"])
            home_key = team_identity(row["home_team"], league_id)
            away_key = team_identity(row["away_team"], league_id)

            if (
                team_count[home_key] < FORM_WINDOW
                or team_count[away_key] < FORM_WINDOW
            ):
                warmup_skipped += 1
                continue

            h5 = _stats(list(team_games[home_key])[-5:])
            h10 = _stats(list(team_games[home_key])[-10:])
            a5 = _stats(list(team_games[away_key])[-5:])
            a10 = _stats(list(team_games[away_key])[-10:])

            hh = list(home_games[home_key])[-5:]
            aa = list(away_games[away_key])[-5:]
            home_venue_win = (
                sum(1 for scored, conceded in hh if scored > conceded) / len(hh)
                if hh else 0.5
            )
            home_venue_goals = (
                sum(scored for scored, _ in hh) / len(hh)
                if hh else 1.5
            )
            away_venue_win = (
                sum(1 for scored, conceded in aa if scored > conceded) / len(aa)
                if aa else 0.35
            )
            away_venue_goals = (
                sum(scored for scored, _ in aa) / len(aa)
                if aa else 1.1
            )

            pair = tuple(sorted((home_key, away_key)))
            previous_h2h = list(h2h_games[pair])[-H2H_WINDOW:]
            if previous_h2h:
                home_wins = goals = btts_count = 0
                for prior_home, prior_hs, prior_as in previous_h2h:
                    if prior_home == home_key:
                        home_goals, away_goals = prior_hs, prior_as
                    else:
                        home_goals, away_goals = prior_as, prior_hs
                    home_wins += int(home_goals > away_goals)
                    goals += home_goals + away_goals
                    btts_count += int(home_goals > 0 and away_goals > 0)
                h2h_n = len(previous_h2h)
                h2h_home_win = home_wins / h2h_n
                h2h_avg_goals = goals / h2h_n
                h2h_btts = btts_count / h2h_n
            else:
                h2h_n = 0
                h2h_home_win = 0.45
                h2h_avg_goals = 2.5
                h2h_btts = 0.5

            (
                comp_home_goals,
                comp_away_goals,
                comp_over15,
                comp_over25,
                comp_btts,
            ) = _league_rates(league_games[league_id])

            home_rating = elo[home_key]
            away_rating = elo[away_key]
            elo_expectation = _elo_expectation(home_rating, away_rating)

            hs = int(row["home_score"])
            aws = int(row["away_score"])

            output.append({
                "date": day.date().isoformat(),
                "league_id": league_id,
                "competition": row["competition"],
                "home_team": row["home_team"],
                "away_team": row["away_team"],
                "source_dataset": row["source_dataset"],
                "source_class": row["source_class"],
                "team_type": row["team_type"],
                "home_win_rate_5": h5["win_rate"],
                "home_win_rate_10": h10["win_rate"],
                "home_draw_rate_5": h5["draw_rate"],
                "home_goals_scored_5": h5["goals_scored"],
                "home_goals_conceded_5": h5["goals_conceded"],
                "home_home_win_rate_5": home_venue_win,
                "home_home_goals_5": home_venue_goals,
                "away_win_rate_5": a5["win_rate"],
                "away_win_rate_10": a10["win_rate"],
                "away_draw_rate_5": a5["draw_rate"],
                "away_goals_scored_5": a5["goals_scored"],
                "away_goals_conceded_5": a5["goals_conceded"],
                "away_away_win_rate_5": away_venue_win,
                "away_away_goals_5": away_venue_goals,
                "h2h_home_win_rate": h2h_home_win,
                "h2h_avg_goals": h2h_avg_goals,
                "h2h_btts_rate": h2h_btts,
                "h2h_meetings": min(h2h_n, H2H_WINDOW) / H2H_WINDOW,
                "competition_home_goals": comp_home_goals,
                "competition_away_goals": comp_away_goals,
                "competition_over_1_5_rate": comp_over15,
                "competition_over_2_5_rate": comp_over25,
                "competition_btts_rate": comp_btts,
                "elo_home_expectation": elo_expectation,
                "elo_diff_scaled": max(
                    -1.0,
                    min(
                        1.0,
                        (
                            home_rating
                            + ELO_HOME_ADVANTAGE
                            - away_rating
                        )
                        / 600.0,
                    ),
                ),
                "home_rest_days_scaled": _rest_days(
                    day, last_played.get(home_key)
                ),
                "away_rest_days_scaled": _rest_days(
                    day, last_played.get(away_key)
                ),
                "national_team_match": float(row["team_type"] == "NATIONAL"),
                "target_match_result": (
                    2 if hs > aws else 1 if hs == aws else 0
                ),
                "target_over_1_5": int(hs + aws > 1),
                "target_over_2_5": int(hs + aws > 2),
                "target_btts": int(hs > 0 and aws > 0),
            })

        # Fold this date into state only after every feature vector exists.
        for row in day_rows:
            league_id = int(row["league_id"])
            home_key = team_identity(row["home_team"], league_id)
            away_key = team_identity(row["away_team"], league_id)
            hs = int(row["home_score"])
            aws = int(row["away_score"])

            team_games[home_key].append((hs, aws))
            team_games[away_key].append((aws, hs))
            home_games[home_key].append((hs, aws))
            away_games[away_key].append((aws, hs))
            pair = tuple(sorted((home_key, away_key)))
            h2h_games[pair].append((home_key, hs, aws))
            league_games[league_id].append((hs, aws))

            home_rating = elo[home_key]
            away_rating = elo[away_key]
            expected = _elo_expectation(home_rating, away_rating)
            actual = 1.0 if hs > aws else 0.5 if hs == aws else 0.0
            delta = ELO_K * (actual - expected)
            elo[home_key] = home_rating + delta
            elo[away_key] = away_rating - delta

            team_count[home_key] += 1
            team_count[away_key] += 1
            last_played[home_key] = day
            last_played[away_key] = day

        i = j

    features = pd.DataFrame(output)
    return features, {
        "input_matches": len(frame),
        "trainable_samples": len(features),
        "warmup_skipped": warmup_skipped,
        "feature_count": len(FEATURE_COLUMNS),
        "source_counts": (
            dict(Counter(features["source_dataset"]))
            if not features.empty else {}
        ),
        "national_team_samples": (
            int((features["team_type"] == "NATIONAL").sum())
            if not features.empty else 0
        ),
    }


def _probability_metrics(y_true, probabilities, classes) -> dict:
    from sklearn.metrics import accuracy_score, log_loss

    y = np.asarray(y_true)
    probs = np.asarray(probabilities, dtype=float)
    class_values = list(classes)
    index_for = {value: index for index, value in enumerate(class_values)}

    one_hot = np.zeros_like(probs, dtype=float)
    for row_index, value in enumerate(y):
        one_hot[row_index, index_for[value]] = 1.0

    prediction_index = probs.argmax(axis=1)
    predicted = np.array([class_values[index] for index in prediction_index])
    confidence = probs.max(axis=1)
    correct = (predicted == y).astype(float)

    ece = 0.0
    for left in np.linspace(0.0, 0.9, 10):
        right = left + 0.1
        mask = (
            (confidence >= left)
            & (confidence <= 1.0 if right >= 1.0 else confidence < right)
        )
        if not mask.any():
            continue
        ece += mask.mean() * abs(correct[mask].mean() - confidence[mask].mean())

    return {
        "accuracy": round(float(accuracy_score(y, predicted)), 6),
        "log_loss": round(
            float(log_loss(y, probs, labels=class_values)),
            6,
        ),
        "brier_multiclass": round(
            float(np.mean(np.sum((probs - one_hot) ** 2, axis=1))),
            6,
        ),
        "top_label_ece": round(float(ece), 6),
    }


def _baseline_probabilities(y_train, n_rows: int, classes) -> np.ndarray:
    train = np.asarray(y_train)
    dist = np.array(
        [float(np.mean(train == value)) for value in classes],
        dtype=float,
    )
    if dist.sum() <= 0:
        dist = np.ones(len(classes), dtype=float)
    dist /= dist.sum()
    return np.tile(dist, (n_rows, 1))


def _aligned_predict_proba(model, X, classes) -> np.ndarray:
    probabilities = model.predict_proba(X)
    model_classes = list(model.classes_)
    out = np.zeros((len(X), len(classes)), dtype=float)
    for index, value in enumerate(classes):
        if value in model_classes:
            out[:, index] = probabilities[:, model_classes.index(value)]
    row_sums = out.sum(axis=1, keepdims=True)
    row_sums[row_sums == 0] = 1.0
    return out / row_sums


def evaluate(features: pd.DataFrame) -> dict:
    if features.empty:
        raise ValueError("No football-first samples are available")

    dates = pd.to_datetime(features["date"], errors="raise")
    split = describe_whole_date_split(
        dates,
        train_frac=0.70,
        calib_frac=0.15,
    )
    i_tr = split["train_end_index"]
    i_ca = split["calib_end_index"]

    X = features[FEATURE_COLUMNS].astype(float).to_numpy()
    train_index = np.arange(0, i_tr)
    calib_index = np.arange(i_tr, i_ca)
    test_index = np.arange(i_ca, len(features))

    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    target_reports = {}

    for target, column in TARGET_COLUMNS.items():
        y = features[column].to_numpy()
        classes = sorted(np.unique(y[train_index]).tolist())
        if len(classes) < 2:
            target_reports[target] = {"status": "INSUFFICIENT_CLASSES"}
            continue

        models = {
            "logistic": Pipeline([
                ("scale", StandardScaler()),
                (
                    "model",
                    LogisticRegression(
                        max_iter=1200,
                        random_state=42,
                    ),
                ),
            ]),
            "hist_gradient_boosting": HistGradientBoostingClassifier(
                learning_rate=0.05,
                max_iter=120,
                max_leaf_nodes=31,
                l2_regularization=0.1,
                random_state=42,
            ),
        }

        calibration_scores = {}
        fitted = {}
        for name, model in models.items():
            model.fit(X[train_index], y[train_index])
            probability = _aligned_predict_proba(
                model,
                X[calib_index],
                classes,
            )
            calibration_scores[name] = _probability_metrics(
                y[calib_index],
                probability,
                classes,
            )
            fitted[name] = model

        selected = min(
            calibration_scores,
            key=lambda name: (
                calibration_scores[name]["log_loss"],
                calibration_scores[name]["brier_multiclass"],
            ),
        )
        model = fitted[selected]
        test_prob = _aligned_predict_proba(
            model,
            X[test_index],
            classes,
        )
        challenger_metrics = _probability_metrics(
            y[test_index],
            test_prob,
            classes,
        )

        baseline_prob = _baseline_probabilities(
            y[train_index],
            len(test_index),
            classes,
        )
        baseline_metrics = _probability_metrics(
            y[test_index],
            baseline_prob,
            classes,
        )

        baseline_loss = baseline_metrics["log_loss"]
        challenger_loss = challenger_metrics["log_loss"]
        skill = (
            (baseline_loss - challenger_loss) / baseline_loss
            if baseline_loss > 0 else 0.0
        )

        test_sources = features.iloc[test_index]["source_dataset"].tolist()
        segment_metrics = {}
        for source in sorted(set(test_sources)):
            local = np.array(
                [value == source for value in test_sources],
                dtype=bool,
            )
            if local.any():
                segment_metrics[source] = {
                    "n": int(local.sum()),
                    **_probability_metrics(
                        y[test_index][local],
                        test_prob[local],
                        classes,
                    ),
                }

        target_reports[target] = {
            "status": "EVALUATED",
            "classes": classes,
            "selected_family": selected,
            "calibration_selection": calibration_scores,
            "test": challenger_metrics,
            "baseline_test": baseline_metrics,
            "log_loss_skill_vs_train_prior": round(float(skill), 6),
            "test_by_source": segment_metrics,
        }

    return {
        "schema": 1,
        "experiment": "football_first_challenger_v1",
        "feature_columns": list(FEATURE_COLUMNS),
        "feature_count": len(FEATURE_COLUMNS),
        "market_price_features_used": [],
        "targets": target_reports,
        "split": split,
        "promotion_enabled": False,
        "live_adjustment_allowed": False,
        "promotion_state": "OFFLINE_ONLY",
        "promotion_blockers": [
            "single_chronological_holdout_only",
            "no_live_shadow_comparison_yet",
            "no_league_market_minimum_sample_promotion_rule_yet",
        ],
    }
