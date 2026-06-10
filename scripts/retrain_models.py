"""
Retrain ALL ML models on historical data — honest edition.

What changed vs the old script (and why):
  - TIME-BASED split (train -> calib -> test in date order) instead of a
    random shuffle. Random splitting on time-series lets the model "see the
    era" and overstates accuracy. This reports real predictive skill.
  - Reports LOG-LOSS, BRIER, and SKILL vs the base rate — not just accuracy.
    Accuracy on an imbalanced target (Over 1.5 is ~75% "yes") looks great
    while the model has learned nothing. Skill-vs-base-rate exposes that.
  - CALIBRATION: fits an isotonic map on a held-out split so the ensemble's
    probabilities mean what they say (a 0.70 wins ~70% of the time).
  - USABLE WEIGHTS: per-model weights are derived from calibration-split
    log-loss and actually consumed by the inference ensemble (the old
    model_weights.json was written and never read).
  - NN saved as a Pipeline(scaler, mlp) so predict_proba works at inference.
    (Previously saved as a (model, scaler) tuple → silently dead at predict.)
  - FAST incremental dataset build (O(n)) replaces the O(n^2) per-row
    DataFrame scans. Same features, minutes -> seconds.

Feature vector and the six base model types are unchanged, so the inference
service stays compatible.

Usage:
    py scripts/retrain_models.py

Outputs:
    models/api_football/<target>_<model_type>.joblib
    models/api_football/calibrators.joblib
    models/api_football/model_weights.json
    models/api_football/meta.json
"""

import json
import sys
from collections import defaultdict, deque
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import warnings
warnings.filterwarnings("ignore")  # silence sklearn feature-name / convergence noise

import joblib
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
MATCHES_CSV = Path("data/api-football/matches.csv")
MODELS_DIR  = Path("models/api_football")
FORM_WINDOW = 5
H2H_WINDOW  = 10

# Time-based split fractions (chronological)
TRAIN_FRAC = 0.70
CALIB_FRAC = 0.15   # calibration + weighting
# remaining 0.15 = test

FEATURE_COLUMNS = [
    "home_win_rate_5", "home_win_rate_10", "home_draw_rate_5",
    "home_goals_scored_5", "home_goals_conceded_5",
    "home_home_win_rate_5", "home_home_goals_5",
    "away_win_rate_5", "away_win_rate_10", "away_draw_rate_5",
    "away_goals_scored_5", "away_goals_conceded_5",
    "away_away_win_rate_5", "away_away_goals_5",
    "h2h_home_win_rate", "h2h_avg_goals", "h2h_btts_rate",
    "h2h_meetings", "league_tier",
]


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
# Feature math — IDENTICAL formulas to the inference index in ml_predictions.
# Computed here from rolling deques maintained in date order (leak-free:
# only strictly-earlier matches are ever in the deque when we compute).
# ---------------------------------------------------------------------------

def _stats_from(games, default):
    """games: list of (scored, conceded). Returns form dict."""
    if not games:
        return default
    wins = draws = gs = gc = 0
    for s, c in games:
        gs += s; gc += c
        if s > c: wins += 1
        elif s == c: draws += 1
    n = len(games)
    return {"win_rate": wins/n, "draw_rate": draws/n,
            "goals_scored": gs/n, "goals_conceded": gc/n}


def build_dataset_fast(df: pd.DataFrame):
    """Incremental O(n) feature build. Mirrors compute_features exactly.

    Processes matches grouped by date: features for a date use only strictly
    earlier matches (matching the old `df[df.date < date]` semantics), then
    that date's matches are added to the rolling state.
    """
    print("Building feature matrix (incremental, fast)...")

    team_games   = defaultdict(lambda: deque(maxlen=20))   # (scored, conceded)
    home_games   = defaultdict(lambda: deque(maxlen=20))   # (home_score, away_score)
    away_games   = defaultdict(lambda: deque(maxlen=20))   # (away_score, home_score)
    h2h_games    = defaultdict(lambda: deque(maxlen=H2H_WINDOW))  # (home_team, hs, as)
    team_count   = defaultdict(int)

    X, y_result, y_o15, y_o25, y_btts = [], [], [], [], []
    skipped = 0

    DEF_TEAM = {"win_rate": 0.5, "draw_rate": 0.25, "goals_scored": 1.2, "goals_conceded": 1.2}

    rows = df.to_dict("records")
    i = 0
    n = len(rows)
    while i < n:
        # Gather all rows sharing this date
        day = rows[i]["date"]
        j = i
        day_rows = []
        while j < n and rows[j]["date"] == day:
            day_rows.append(rows[j]); j += 1

        # 1) Compute features for the day using current (strictly-earlier) state
        for r in day_rows:
            home, away = r["home_team"], r["away_team"]
            tier = int(r.get("league_tier", 1)) if not pd.isna(r.get("league_tier", 1)) else 1

            if team_count[home] < 5 or team_count[away] < 5:
                r["_skip"] = True
                skipped += 1
                continue
            r["_skip"] = False

            h5  = _stats_from(list(team_games[home])[-5:], DEF_TEAM)
            h10 = _stats_from(list(team_games[home])[-10:], DEF_TEAM)
            a5  = _stats_from(list(team_games[away])[-5:], DEF_TEAM)
            a10 = _stats_from(list(team_games[away])[-10:], DEF_TEAM)

            hh = list(home_games[home])[-5:]
            if hh:
                hh_wr = sum(1 for hs, as_ in hh if hs > as_) / len(hh)
                hh_gs = sum(hs for hs, _ in hh) / len(hh)
            else:
                hh_wr, hh_gs = 0.5, 1.5

            aa = list(away_games[away])[-5:]
            if aa:
                aa_wr = sum(1 for as_, hs in aa if as_ > hs) / len(aa)
                aa_gs = sum(as_ for as_, _ in aa) / len(aa)
            else:
                aa_wr, aa_gs = 0.35, 1.1

            hk = (home, away) if home <= away else (away, home)
            h2h = list(h2h_games[hk])[-H2H_WINDOW:]
            if h2h:
                hw = btts = tg = 0
                for mh, hs, as_ in h2h:
                    hg = hs if mh == home else as_
                    ag = as_ if mh == home else hs
                    tg += hg + ag
                    if hg > ag: hw += 1
                    if hg > 0 and ag > 0: btts += 1
                ng = len(h2h)
                h2h_hwr, h2h_ag, h2h_btts, h2h_n = hw/ng, tg/ng, btts/ng, ng
            else:
                h2h_hwr, h2h_ag, h2h_btts, h2h_n = 0.45, 2.5, 0.5, 0

            feats = [
                h5["win_rate"], h10["win_rate"], h5["draw_rate"],
                h5["goals_scored"], h5["goals_conceded"],
                hh_wr, hh_gs,
                a5["win_rate"], a10["win_rate"], a5["draw_rate"],
                a5["goals_scored"], a5["goals_conceded"],
                aa_wr, aa_gs,
                h2h_hwr, h2h_ag, h2h_btts,
                min(h2h_n, 10) / 10,
                tier / 2,
            ]
            hg, ag = r["home_score"], r["away_score"]
            X.append(feats)
            y_result.append(2 if hg > ag else (1 if hg == ag else 0))
            y_o15.append(1 if hg + ag > 1 else 0)
            y_o25.append(1 if hg + ag > 2 else 0)
            y_btts.append(1 if hg > 0 and ag > 0 else 0)

        # 2) Now fold the day's matches into rolling state
        for r in day_rows:
            home, away = r["home_team"], r["away_team"]
            hg, ag = r["home_score"], r["away_score"]
            team_games[home].append((hg, ag))
            team_games[away].append((ag, hg))
            home_games[home].append((hg, ag))
            away_games[away].append((ag, hg))
            hk = (home, away) if home <= away else (away, home)
            h2h_games[hk].append((home, hg, ag))
            team_count[home] += 1
            team_count[away] += 1

        i = j

    print(f"  Built {len(X):,} samples (skipped {skipped:,} with <5 games of history)")
    return (np.array(X, dtype=float),
            np.array(y_result), np.array(y_o15), np.array(y_o25), np.array(y_btts))


# ---------------------------------------------------------------------------
# Model trainers (NN now wrapped in a Pipeline so predict_proba works)
# ---------------------------------------------------------------------------

def train_xgboost(Xtr, ytr):
    from xgboost import XGBClassifier
    nc = len(np.unique(ytr))
    return XGBClassifier(
        n_estimators=300, max_depth=5, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8,
        objective="multi:softprob" if nc > 2 else "binary:logistic",
        num_class=nc if nc > 2 else None,
        eval_metric="mlogloss" if nc > 2 else "logloss",
        random_state=42, n_jobs=-1,
    ).fit(Xtr, ytr)


def train_lightgbm(Xtr, ytr):
    import lightgbm as lgb
    nc = len(np.unique(ytr))
    return lgb.LGBMClassifier(
        n_estimators=300, max_depth=5, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8,
        objective="multiclass" if nc > 2 else "binary",
        num_class=nc if nc > 2 else None,
        random_state=42, n_jobs=-1, verbose=-1,
    ).fit(Xtr, ytr)


def train_catboost(Xtr, ytr):
    from catboost import CatBoostClassifier
    nc = len(np.unique(ytr))
    return CatBoostClassifier(
        iterations=300, depth=5, learning_rate=0.05,
        loss_function="MultiClass" if nc > 2 else "Logloss",
        random_seed=42, verbose=0,
    ).fit(Xtr, ytr)


def train_random_forest(Xtr, ytr):
    from sklearn.ensemble import RandomForestClassifier
    return RandomForestClassifier(
        n_estimators=500, max_depth=12, min_samples_split=5, min_samples_leaf=2,
        max_features="sqrt", class_weight="balanced", random_state=42, n_jobs=-1,
    ).fit(Xtr, ytr)


def train_extra_trees(Xtr, ytr):
    from sklearn.ensemble import ExtraTreesClassifier
    return ExtraTreesClassifier(
        n_estimators=500, max_depth=12, min_samples_split=5, min_samples_leaf=2,
        max_features="sqrt", class_weight="balanced", random_state=42, n_jobs=-1,
    ).fit(Xtr, ytr)


def train_neural_network(Xtr, ytr):
    from sklearn.neural_network import MLPClassifier
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import Pipeline
    # Pipeline keeps the scaler with the model so predict_proba works directly
    # at inference (no special-case tuple handling).
    return Pipeline([
        ("scaler", StandardScaler()),
        ("mlp", MLPClassifier(
            hidden_layer_sizes=(128, 64, 32), activation="relu", solver="adam",
            learning_rate="adaptive", learning_rate_init=0.001, max_iter=500,
            early_stopping=True, validation_fraction=0.1, n_iter_no_change=20,
            random_state=42,
        )),
    ]).fit(Xtr, ytr)


TRAINERS = [
    ("xgb", train_xgboost),
    ("lgbm", train_lightgbm),
    ("catboost", train_catboost),
    ("rf", train_random_forest),
    ("et", train_extra_trees),
    ("nn", train_neural_network),
]


# ---------------------------------------------------------------------------
# Calibration + weighting helpers
# ---------------------------------------------------------------------------

def _aligned_proba(model, X, classes):
    """predict_proba aligned to a fixed class ordering."""
    p = model.predict_proba(X)
    model_classes = list(model.classes_)
    if model_classes == list(classes):
        return p
    out = np.zeros((p.shape[0], len(classes)))
    for j, c in enumerate(classes):
        if c in model_classes:
            out[:, j] = p[:, model_classes.index(c)]
    return out


def _baseline_logloss(y, classes):
    """Log-loss of always predicting the empirical class distribution."""
    from sklearn.metrics import log_loss
    dist = np.array([(y == c).mean() for c in classes])
    probs = np.tile(dist, (len(y), 1))
    return log_loss(y, probs, labels=classes)


# ---------------------------------------------------------------------------
# Train one target end-to-end
# ---------------------------------------------------------------------------

def train_target(label, X, y, idx_tr, idx_ca, idx_te, out_dir):
    from sklearn.metrics import accuracy_score, log_loss, brier_score_loss
    from sklearn.isotonic import IsotonicRegression

    classes = sorted(np.unique(y).tolist())
    n_classes = len(classes)
    Xtr, ytr = X[idx_tr], y[idx_tr]
    Xca, yca = X[idx_ca], y[idx_ca]
    Xte, yte = X[idx_te], y[idx_te]

    base_rate = max((yte == c).mean() for c in classes)
    base_ll = _baseline_logloss(yte, classes)

    print(f"\n{'='*64}")
    print(f"  TARGET: {label}  ({n_classes} classes)")
    print(f"  train={len(Xtr):,}  calib={len(Xca):,}  test={len(Xte):,}")
    print(f"  base rate (majority): {base_rate:.3f}   baseline log-loss: {base_ll:.4f}")
    print(f"{'='*64}")

    models = {}
    weights = {}
    accuracies = {}
    print(f"  {'model':10s}{'acc':>8s}{'logloss':>10s}{'skill%':>9s}")
    for tag, fn in TRAINERS:
        try:
            m = fn(Xtr, ytr)
        except Exception as e:
            print(f"  {tag:10s}  FAILED: {e}")
            continue
        # Calibration-split log-loss drives the ensemble weight
        p_ca = _aligned_proba(m, Xca, classes)
        ll_ca = log_loss(yca, p_ca, labels=classes)
        # Test metrics (honest, time-held-out)
        p_te = _aligned_proba(m, Xte, classes)
        acc = accuracy_score(yte, m.predict(Xte))
        ll_te = log_loss(yte, p_te, labels=classes)
        skill = (base_ll - ll_te) / base_ll * 100  # % log-loss reduction vs base

        models[tag] = m
        weights[tag] = 1.0 / max(ll_ca, 1e-6)
        accuracies[f"{label}_{tag}"] = round(acc, 4)
        joblib.dump(m, out_dir / f"{label}_{tag}.joblib")
        print(f"  {tag:10s}{acc:>8.3f}{ll_te:>10.4f}{skill:>8.1f}%")

    if not models:
        return {}, {}, None

    # Normalize weights
    wsum = sum(weights.values())
    weights = {k: v / wsum for k, v in weights.items()}

    # Build the weighted ensemble probability on calib + test splits
    def ensemble_proba(Xset):
        agg = np.zeros((Xset.shape[0], n_classes))
        for tag, m in models.items():
            agg += weights[tag] * _aligned_proba(m, Xset, classes)
        return agg

    p_ca_ens = ensemble_proba(Xca)
    p_te_ens = ensemble_proba(Xte)

    from sklearn.metrics import accuracy_score as _acc, log_loss as _ll
    ens_acc = _acc(yte, [classes[i] for i in p_te_ens.argmax(1)])
    ens_ll = _ll(yte, p_te_ens, labels=classes)
    ens_skill = (base_ll - ens_ll) / base_ll * 100

    # Fit isotonic calibrators per class on the calibration split, then
    # evaluate calibrated ensemble on test.
    calibrators = []
    for j, c in enumerate(classes):
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        iso.fit(p_ca_ens[:, j], (yca == c).astype(float))
        calibrators.append(iso)

    def calibrate(P):
        cal = np.column_stack([calibrators[j].predict(P[:, j]) for j in range(n_classes)])
        row = cal.sum(1, keepdims=True)
        row[row == 0] = 1.0
        return cal / row

    p_te_cal = calibrate(p_te_ens)
    cal_ll = _ll(yte, p_te_cal, labels=classes)
    cal_skill = (base_ll - cal_ll) / base_ll * 100

    print(f"  {'-'*40}")
    print(f"  {'ENSEMBLE':10s}{ens_acc:>8.3f}{ens_ll:>10.4f}{ens_skill:>8.1f}%")
    print(f"  {'+calib':10s}{'':>8s}{cal_ll:>10.4f}{cal_skill:>8.1f}%")

    calib_payload = {
        "classes": classes,
        "weights": weights,
        "calibrators": calibrators,
    }
    return accuracies, {label: {"weights": weights, "classes": classes,
                                "ensemble_test_logloss": round(ens_ll, 4),
                                "calibrated_test_logloss": round(cal_ll, 4),
                                "baseline_test_logloss": round(base_ll, 4),
                                "skill_pct": round(cal_skill, 1)}}, calib_payload


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not MATCHES_CSV.exists():
        print(f"ERROR: {MATCHES_CSV} not found. Run fetch first.")
        sys.exit(1)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    df = load_data()
    X, y_result, y_o15, y_o25, y_btts = build_dataset_fast(df)

    n = len(X)
    # Chronological split (X is already in date order from the build)
    i_tr = int(n * TRAIN_FRAC)
    i_ca = int(n * (TRAIN_FRAC + CALIB_FRAC))
    idx_tr = np.arange(0, i_tr)
    idx_ca = np.arange(i_tr, i_ca)
    idx_te = np.arange(i_ca, n)

    print(f"\nTime-based split: train[0:{i_tr:,}]  calib[{i_tr:,}:{i_ca:,}]  test[{i_ca:,}:{n:,}]")
    print(f"  (oldest matches train the model; newest test it — honest holdout)")

    print(f"\nClass balance (full):")
    print(f"  Home/Draw/Away: {(y_result==2).mean():.1%}/{(y_result==1).mean():.1%}/{(y_result==0).mean():.1%}")
    print(f"  Over1.5/Over2.5/BTTS: {y_o15.mean():.1%}/{y_o25.mean():.1%}/{y_btts.mean():.1%}")

    all_acc = {}
    weights_meta = {}
    calibrators = {}

    for label, y in (("match_result", y_result), ("over_1_5", y_o15),
                     ("over_2_5", y_o25), ("btts", y_btts)):
        acc, wmeta, calib = train_target(label, X, y, idx_tr, idx_ca, idx_te, MODELS_DIR)
        all_acc.update(acc)
        weights_meta.update(wmeta)
        if calib is not None:
            calibrators[label] = calib

    # Statistical models (ELO + Dixon-Coles) — train on ALL data
    print(f"\n{'='*64}\n  STATISTICAL MODELS\n{'='*64}")
    matches_for_stat = [
        {"home_team": r["home_team"], "away_team": r["away_team"],
         "home_goals": int(r["home_score"]), "away_goals": int(r["away_score"]),
         "date": str(r["date"])}
        for r in df.to_dict("records")
    ]
    try:
        from ml.elo_model import EloRatingSystem
        elo = EloRatingSystem(); elo.train(matches_for_stat)
        elo.save(str(MODELS_DIR / "elo_ratings.json"))
        print(f"  ELO saved ({len(elo.ratings)} teams)")
    except Exception as e:
        print(f"  ELO failed: {e}")
    try:
        from ml.dixon_coles_model import DixonColesModel
        dc = DixonColesModel(); dc.train(matches_for_stat[-2000:])
        dc.save(str(MODELS_DIR / "dixon_coles.json"))
        print(f"  Dixon-Coles saved ({len(dc.teams)} teams)")
    except Exception as e:
        print(f"  Dixon-Coles failed: {e}")

    # Save calibrators (joblib — contains fitted IsotonicRegression objects)
    joblib.dump(calibrators, MODELS_DIR / "calibrators.joblib")
    print(f"\n  Calibrators saved -> {MODELS_DIR / 'calibrators.joblib'}")

    # Save weights + meta
    with open(MODELS_DIR / "model_weights.json", "w") as f:
        json.dump({"accuracies": all_acc, "ensemble": weights_meta}, f, indent=2)

    meta = {
        "feature_columns": FEATURE_COLUMNS,
        "form_window": FORM_WINDOW, "h2h_window": H2H_WINDOW,
        "trained_at": datetime.utcnow().isoformat(),
        "n_samples": int(n),
        "split": {"train": int(i_tr), "calib": int(i_ca - i_tr), "test": int(n - i_ca)},
        "models": sorted(all_acc.keys()),
        "model_types": [t for t, _ in TRAINERS],
        "targets": ["match_result", "over_1_5", "over_2_5", "btts"],
        "result_classes": {0: "Away Win", 1: "Draw", 2: "Home Win"},
        "calibrated": True,
        "ensemble": weights_meta,
    }
    with open(MODELS_DIR / "meta.json", "w") as f:
        json.dump(meta, f, indent=2)

    # Final honest summary
    print(f"\n{'='*64}\n  SKILL SUMMARY (calibrated ensemble, time-held-out test)\n{'='*64}")
    print(f"  {'target':16s}{'skill%':>10s}  {'verdict'}")
    for label, m in weights_meta.items():
        skill = m["skill_pct"]
        verdict = "STRONG" if skill >= 5 else ("weak" if skill >= 1 else "NO EDGE — base rate only")
        print(f"  {label:16s}{skill:>9.1f}%  {verdict}")
    print(f"\n  Models: {len(all_acc)}   Restart server to load the calibrated ensemble.")


if __name__ == "__main__":
    main()
