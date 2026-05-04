"""
Retrain all ML models on API-Football historical data.

Reads data/api-football/matches.csv (produced by fetch_history.py),
engineers features, trains XGBoost + LightGBM + CatBoost models,
ELO ratings, and Dixon-Coles parameters, and writes to models/.

The feature vector is defined ONCE here and mirrored exactly in
services/advanced_prediction_service.py ? that's what makes
predictions consistent with training.

Usage:
    py scripts/retrain_models.py

Outputs:
    models/api_football/match_result_xgb.joblib
    models/api_football/over_2_5_xgb.joblib
    models/api_football/btts_xgb.joblib
    models/api_football/match_result_lgbm.joblib
    models/api_football/over_2_5_lgbm.joblib
    models/api_football/btts_lgbm.joblib
    models/api_football/feature_columns.json
"""

import json
import sys
from pathlib import Path
from datetime import datetime

import joblib
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
MATCHES_CSV  = Path("data/api-football/matches.csv")
MODELS_DIR   = Path("models/api_football")
FORM_WINDOW  = 5    # last N games for form features
H2H_WINDOW   = 10   # last N head-to-head meetings

# ---------------------------------------------------------------------------

def load_data() -> pd.DataFrame:
    print(f"Loading {MATCHES_CSV} ...")
    df = pd.read_csv(MATCHES_CSV, low_memory=False)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "home_team", "away_team", "home_score", "away_score"])
    df["home_score"] = df["home_score"].astype(int)
    df["away_score"] = df["away_score"].astype(int)
    df = df.sort_values("date").reset_index(drop=True)
    print(f"  {len(df):,} finished matches across {df['league_name'].nunique()} leagues")
    return df


# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------

def _team_stats(df_past: pd.DataFrame, team: str, n: int) -> dict:
    """Rolling form stats for a team from their last N games."""
    games = df_past[
        (df_past["home_team"] == team) | (df_past["away_team"] == team)
    ].tail(n)

    if len(games) == 0:
        return {
            "win_rate": 0.5, "draw_rate": 0.25,
            "goals_scored": 1.2, "goals_conceded": 1.2,
            "n_games": 0,
        }

    wins = draws = goals_scored = goals_conceded = 0
    for _, r in games.iterrows():
        if r["home_team"] == team:
            gs, gc = r["home_score"], r["away_score"]
        else:
            gs, gc = r["away_score"], r["home_score"]
        goals_scored    += gs
        goals_conceded  += gc
        if gs > gc:
            wins  += 1
        elif gs == gc:
            draws += 1

    n_games = len(games)
    return {
        "win_rate":        wins  / n_games,
        "draw_rate":       draws / n_games,
        "goals_scored":    goals_scored  / n_games,
        "goals_conceded":  goals_conceded / n_games,
        "n_games":         n_games,
    }


def _team_home_stats(df_past: pd.DataFrame, team: str, n: int) -> dict:
    games = df_past[df_past["home_team"] == team].tail(n)
    if len(games) == 0:
        return {"win_rate": 0.5, "goals_scored": 1.5}
    wins = sum(1 for _, r in games.iterrows() if r["home_score"] > r["away_score"])
    goals = sum(r["home_score"] for _, r in games.iterrows())
    n_g = len(games)
    return {"win_rate": wins / n_g, "goals_scored": goals / n_g}


def _team_away_stats(df_past: pd.DataFrame, team: str, n: int) -> dict:
    games = df_past[df_past["away_team"] == team].tail(n)
    if len(games) == 0:
        return {"win_rate": 0.35, "goals_scored": 1.1}
    wins = sum(1 for _, r in games.iterrows() if r["away_score"] > r["home_score"])
    goals = sum(r["away_score"] for _, r in games.iterrows())
    n_g = len(games)
    return {"win_rate": wins / n_g, "goals_scored": goals / n_g}


def _h2h_stats(df_past: pd.DataFrame, home: str, away: str, n: int) -> dict:
    h2h = df_past[
        ((df_past["home_team"] == home) & (df_past["away_team"] == away)) |
        ((df_past["home_team"] == away) & (df_past["away_team"] == home))
    ].tail(n)

    if len(h2h) == 0:
        return {"home_win_rate": 0.45, "avg_goals": 2.5, "btts_rate": 0.5, "n": 0}

    home_wins = btts = total_goals = 0
    for _, r in h2h.iterrows():
        if r["home_team"] == home:
            hg, ag = r["home_score"], r["away_score"]
        else:
            hg, ag = r["away_score"], r["home_score"]
        total_goals += hg + ag
        if hg > ag:
            home_wins += 1
        if hg > 0 and ag > 0:
            btts += 1

    n_g = len(h2h)
    return {
        "home_win_rate": home_wins / n_g,
        "avg_goals":     total_goals / n_g,
        "btts_rate":     btts / n_g,
        "n":             n_g,
    }


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
    "league_tier",
]


def compute_features(home: str, away: str, date, df_past: pd.DataFrame,
                     league_tier: int = 1) -> list:
    """Build feature vector ? must mirror advanced_prediction_service._compute_api_features()."""
    h5  = _team_stats(df_past, home, 5)
    h10 = _team_stats(df_past, home, 10)
    hh5 = _team_home_stats(df_past, home, 5)
    a5  = _team_stats(df_past, away, 5)
    a10 = _team_stats(df_past, away, 10)
    aa5 = _team_away_stats(df_past, away, 5)
    h2h = _h2h_stats(df_past, home, away, H2H_WINDOW)

    return [
        h5["win_rate"],
        h10["win_rate"],
        h5["draw_rate"],
        h5["goals_scored"],
        h5["goals_conceded"],
        hh5["win_rate"],
        hh5["goals_scored"],
        a5["win_rate"],
        a10["win_rate"],
        a5["draw_rate"],
        a5["goals_scored"],
        a5["goals_conceded"],
        aa5["win_rate"],
        aa5["goals_scored"],
        h2h["home_win_rate"],
        h2h["avg_goals"],
        h2h["btts_rate"],
        min(h2h["n"], 10) / 10,   # normalised 0-1
        league_tier / 2,           # normalised 0-1 (tier 0=Europe, 1=top, 2=second)
    ]


# ---------------------------------------------------------------------------
# Build dataset
# ---------------------------------------------------------------------------

def build_dataset(df: pd.DataFrame) -> tuple:
    """
    Compute features + targets for every match in df (using only past data).
    Skips the first 20 matches per team to ensure enough history.
    Returns X (numpy), y_result, y_over25, y_btts.
    """
    print("Building feature matrix (this takes a few minutes)...")

    X, y_result, y_over25, y_btts = [], [], [], []
    skipped = 0

    for idx, row in df.iterrows():
        if idx % 5000 == 0 and idx > 0:
            print(f"  {idx:,}/{len(df):,} matches processed...")

        home  = row["home_team"]
        away  = row["away_team"]
        date  = row["date"]
        tier  = int(row.get("league_tier", 1))

        df_past = df[df["date"] < date]

        # Skip if either team has fewer than 5 historical games
        home_count = ((df_past["home_team"] == home) | (df_past["away_team"] == home)).sum()
        away_count = ((df_past["home_team"] == away) | (df_past["away_team"] == away)).sum()
        if home_count < 5 or away_count < 5:
            skipped += 1
            continue

        feats = compute_features(home, away, date, df_past, tier)
        X.append(feats)

        # Targets
        hg, ag = row["home_score"], row["away_score"]
        y_result.append(2 if hg > ag else (1 if hg == ag else 0))
        y_over25.append(1 if hg + ag > 2 else 0)
        y_btts.append(1 if hg > 0 and ag > 0 else 0)

    print(f"  Built {len(X):,} training samples (skipped {skipped:,} with insufficient history)")
    return np.array(X), np.array(y_result), np.array(y_over25), np.array(y_btts)


# ---------------------------------------------------------------------------
# Train & evaluate
# ---------------------------------------------------------------------------

def train_xgboost(X_train, y_train, label: str):
    try:
        from xgboost import XGBClassifier
    except ImportError:
        print("  xgboost not installed ? skipping XGBoost")
        return None

    n_classes = len(np.unique(y_train))
    objective = "multi:softprob" if n_classes > 2 else "binary:logistic"

    model = XGBClassifier(
        n_estimators=300,
        max_depth=5,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        objective=objective,
        num_class=n_classes if n_classes > 2 else None,
        eval_metric="mlogloss" if n_classes > 2 else "logloss",
        use_label_encoder=False,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_train, y_train)
    return model


def train_lightgbm(X_train, y_train, label: str):
    try:
        import lightgbm as lgb
    except ImportError:
        print("  lightgbm not installed ? skipping LightGBM")
        return None

    n_classes = len(np.unique(y_train))
    objective = "multiclass" if n_classes > 2 else "binary"

    model = lgb.LGBMClassifier(
        n_estimators=300,
        max_depth=5,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        objective=objective,
        num_class=n_classes if n_classes > 2 else None,
        random_state=42,
        n_jobs=-1,
        verbose=-1,
    )
    model.fit(X_train, y_train)
    return model



def train_catboost(X_train, y_train, label: str):
    try:
        from catboost import CatBoostClassifier
    except ImportError:
        print("  catboost not installed - skipping CatBoost")
        return None

    n_classes = len(np.unique(y_train))
    loss = "MultiClass" if n_classes > 2 else "Logloss"

    model = CatBoostClassifier(
        iterations=300,
        depth=5,
        learning_rate=0.05,
        loss_function=loss,
        random_seed=42,
        verbose=0,
    )
    model.fit(X_train, y_train)
    return model

def evaluate(model, X_test, y_test, name: str):
    from sklearn.metrics import accuracy_score
    preds = model.predict(X_test)
    acc   = accuracy_score(y_test, preds)
    print(f"    {name}: accuracy = {acc:.3f}")
    return acc


def train_and_save(X, y, label: str, out_dir: Path):
    from sklearn.model_selection import train_test_split

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.15, random_state=42, stratify=y
    )

    print(f"\n  Training {label}  ({len(np.unique(y))} classes, {len(X_train):,} samples)")

    xgb_model  = train_xgboost(X_train, y_train, label)
    lgbm_model = train_lightgbm(X_train, y_train, label)
    cb_model   = train_catboost(X_train, y_train, label)

    for model, name in [(xgb_model, "xgb"), (lgbm_model, "lgbm"), (cb_model, "catboost")]:
        if model is None:
            continue
        evaluate(model, X_test, y_test, name)
        path = out_dir / f"{label}_{name}.joblib"
        joblib.dump(model, path)
        print(f"    Saved ? {path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not MATCHES_CSV.exists():
        print(f"ERROR: {MATCHES_CSV} not found.")
        print("Run  py scripts/fetch_history.py  first.")
        sys.exit(1)

    try:
        from sklearn.model_selection import train_test_split
    except ImportError:
        print("ERROR: scikit-learn not installed.  pip install scikit-learn xgboost lightgbm joblib")
        sys.exit(1)

    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    df = load_data()
    X, y_result, y_over25, y_btts = build_dataset(df)

    print(f"\nDataset summary:")
    print(f"  Samples   : {len(X):,}")
    print(f"  Home wins : {(y_result == 2).sum():,}  ({(y_result == 2).mean():.1%})")
    print(f"  Draws     : {(y_result == 1).sum():,}  ({(y_result == 1).mean():.1%})")
    print(f"  Away wins : {(y_result == 0).sum():,}  ({(y_result == 0).mean():.1%})")
    print(f"  Over 2.5  : {y_over25.sum():,}  ({y_over25.mean():.1%})")
    print(f"  BTTS      : {y_btts.sum():,}  ({y_btts.mean():.1%})")

    train_and_save(X, y_result, "match_result", MODELS_DIR)
    train_and_save(X, y_over25, "over_2_5",     MODELS_DIR)
    train_and_save(X, y_btts,   "btts",         MODELS_DIR)

    # Train statistical models (ELO + Dixon-Coles)
    print("\nTraining statistical models...")
    matches_for_stat = []
    for _, r in df.iterrows():
        try:
            matches_for_stat.append({
                "home_team": r["home_team"],
                "away_team": r["away_team"],
                "home_goals": int(r["home_score"]),
                "away_goals": int(r["away_score"]),
                "date": str(r["date"]),
            })
        except (ValueError, KeyError):
            continue

    try:
        from ml.elo_model import EloRatingSystem
        elo = EloRatingSystem()
        elo.train(matches_for_stat)
        elo_path = MODELS_DIR / "elo_ratings.json"
        elo.save(str(elo_path))
        print(f"  ELO ratings saved ({len(elo.ratings)} teams)")
    except Exception as e:
        print(f"  ELO training failed: {e}")

    try:
        from ml.dixon_coles_model import DixonColesModel
        dc = DixonColesModel()
        dc.train(matches_for_stat[-2000:])
        dc_path = MODELS_DIR / "dixon_coles.json"
        dc.save(str(dc_path))
        print(f"  Dixon-Coles saved ({len(dc.teams)} teams)")
    except Exception as e:
        print(f"  Dixon-Coles training failed: {e}")

    # Save feature columns so prediction code knows the vector layout
    meta = {
        "feature_columns": FEATURE_COLUMNS,
        "form_window":     FORM_WINDOW,
        "h2h_window":      H2H_WINDOW,
        "trained_at":      datetime.utcnow().isoformat(),
        "n_samples":       len(X),
        "models": ["match_result_xgb", "match_result_lgbm", "match_result_catboost",
                   "over_2_5_xgb", "over_2_5_lgbm", "over_2_5_catboost",
                   "btts_xgb", "btts_lgbm", "btts_catboost"],
        "result_classes":  {0: "Away Win", 1: "Draw", 2: "Home Win"},
    }
    meta_path = MODELS_DIR / "meta.json"
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    print(f"\n?  All models saved to {MODELS_DIR}/")
    print(f"   Feature columns: {len(FEATURE_COLUMNS)}")
    print(f"\nNext step: restart the server ? predictions will use the new models automatically.")


if __name__ == "__main__":
    main()
