"""
The trained ensemble, wired back into the live path.

Six model families (XGBoost, LightGBM, CatBoost, random forest, extra trees, a
small neural net) across four targets — match result, over 1.5, over 2.5, both
teams to score — trained on 64,218 matches and isotonic-calibrated at training
time. `models/api_football/`.

They have been sitting unused because the live engine was rebuilt around ESPN
while these were trained on API-Football features. Nothing imported them. This
reconnects them by rebuilding those 25 features from the ESPN feed instead.

**Nothing here moves a published number yet.** `predict_fixture` returns a
second opinion that is recorded alongside the model already in use, and an
evaluation endpoint compares the two against settled results. The ensemble
earns its way in on that evidence or it does not go in at all — the accuracies
in model_weights.json say match result is 50.3% on a three-way choice where
always picking the home side is about 46%, which is real skill but not much of
it, and not something to hand the published card on trust.
"""

import json
import logging
import math
import os
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

MODEL_DIR = Path(__file__).parent.parent / "models" / "api_football"
META_PATH = MODEL_DIR / "meta.json"

# Families to load per target. Random forest and extra trees are deliberately
# skipped: they are 60-100MB each, score below the boosted models on every
# target, and the container has limited memory.
FAMILIES = ("xgb", "lgbm", "catboost", "nn")

# BTTS is excluded. Its measured skill is 0.7% — inside the noise — and its
# output is visibly degenerate on the fixtures that make up most of our card:
# on an unpriced match the four families return P(yes) between 0.002 and 0.20,
# and the isotonic layer then floors the blend to exactly 0. A market that
# lands about half the time cannot be predicted at 0%.
TARGETS = ("match_result", "over_1_5", "over_2_5")

# The models only get used where a bookmaker has priced the match.
#
# Six of the 25 features are market probabilities. With no odds they are all
# zero, and although `mkt_has_odds` flags that, the models clearly do not treat
# it as "missing" so much as "extreme": on unpriced fixtures Over 1.5 comes out
# at 90% against the Poisson model's 73%, Over 2.5 at 76% where the base rate
# is nearer 50%, and BTTS collapses to nothing. That is extrapolation outside
# the training distribution, not insight.
#
# 66% of fixtures carry odds, which is where the ensemble has something to say.
# On the rest the existing market-anchored model stands alone, as it already
# does today.
REQUIRE_MARKET = True

# Rough league strength tiers, used for the `league_tier` feature. Anything
# unmapped is treated as mid-table, which is where most of our slate sits.
TIER_1 = {"eng.1", "esp.1", "ger.1", "ita.1", "fra.1"}
TIER_2 = {"eng.2", "esp.2", "ger.2", "ita.2", "por.1", "ned.1", "bel.1",
          "tur.1", "sco.1", "rus.1", "usa.1", "mex.1", "bra.1", "arg.1"}

_LOCK = threading.Lock()
_STATE: dict = {"loaded": False, "models": {}, "calibrators": {}, "meta": None}


def is_available() -> bool:
    return META_PATH.exists()


def _load() -> dict:
    """Load models once, on first use. Thread-safe."""
    if _STATE["loaded"]:
        return _STATE
    with _LOCK:
        if _STATE["loaded"]:
            return _STATE
        try:
            import joblib
            meta = json.loads(META_PATH.read_text())
            models: dict[str, list] = {}
            for target in TARGETS:
                loaded = []
                for fam in FAMILIES:
                    path = MODEL_DIR / f"{target}_{fam}.joblib"
                    if not path.exists():
                        continue
                    try:
                        loaded.append((fam, joblib.load(path)))
                    except Exception as e:
                        logger.warning(f"ml: {path.name} failed to load: {e}")
                if loaded:
                    models[target] = loaded

            calibrators = {}
            cal_path = MODEL_DIR / "calibrators.joblib"
            if cal_path.exists():
                try:
                    calibrators = joblib.load(cal_path) or {}
                except Exception as e:
                    logger.warning(f"ml: calibrators failed to load: {e}")

            _STATE.update({"loaded": True, "models": models,
                           "calibrators": calibrators, "meta": meta})
            logger.info(
                "ml ensemble loaded: "
                + ", ".join(f"{t}({len(m)})" for t, m in models.items())
            )
        except Exception as e:
            logger.error(f"ml ensemble unavailable: {e}")
            _STATE.update({"loaded": True, "models": {}, "calibrators": {}, "meta": None})
    return _STATE


def _tier(slug: str) -> int:
    if slug in TIER_1:
        return 1
    if slug in TIER_2:
        return 2
    return 3


def build_features(fixture: dict, index) -> list[float] | None:
    """The 25-feature vector for one fixture, in the trained column order."""
    state = _load()
    meta = state.get("meta")
    if not meta:
        return None

    home = fixture["home"]["name"]
    away = fixture["away"]["name"]
    hf = index.team_form(home, "home")
    af = index.team_form(away, "away")
    h2h = index.head_to_head(home, away, meta.get("h2h_window", 10))

    odds = fixture.get("odds") or {}
    implied = odds.get("implied") or {}
    has_odds = 1.0 if implied else 0.0
    over25 = odds.get("implied_over")

    values = {
        "home_win_rate_5": hf["win_rate_5"],
        "home_win_rate_10": hf["win_rate_10"],
        "home_draw_rate_5": hf["draw_rate_5"],
        "home_goals_scored_5": hf["goals_scored_5"],
        "home_goals_conceded_5": hf["goals_conceded_5"],
        "home_home_win_rate_5": hf["venue_win_rate_5"],
        "home_home_goals_5": hf["venue_goals_5"],
        "away_win_rate_5": af["win_rate_5"],
        "away_win_rate_10": af["win_rate_10"],
        "away_draw_rate_5": af["draw_rate_5"],
        "away_goals_scored_5": af["goals_scored_5"],
        "away_goals_conceded_5": af["goals_conceded_5"],
        "away_away_win_rate_5": af["venue_win_rate_5"],
        "away_away_goals_5": af["venue_goals_5"],
        "h2h_home_win_rate": h2h["home_win_rate"],
        "h2h_avg_goals": h2h["avg_goals"],
        "h2h_btts_rate": h2h["btts_rate"],
        "h2h_meetings": float(h2h["meetings"]),
        "league_tier": float(_tier(fixture.get("league_slug", ""))),
        "mkt_prob_home": float(implied.get("home_win") or 0.0),
        "mkt_prob_draw": float(implied.get("draw") or 0.0),
        "mkt_prob_away": float(implied.get("away_win") or 0.0),
        "mkt_has_odds": has_odds,
        "mkt_prob_over25": float(over25 or 0.0),
        "mkt_ou_has": 1.0 if over25 else 0.0,
    }

    # Trained column order is authoritative; a missing column becomes 0, which
    # is how the training pipeline encoded absence.
    return [float(values.get(col, 0.0)) for col in meta["feature_columns"]]


# Whether the isotonic layer actually helped, per target, measured on held-out
# data at training time (model_weights.json):
#
#     target        raw ensemble   calibrated   use
#     match_result      1.0046       1.0106     raw
#     over_1_5          0.5457       0.5354     calibrated
#     over_2_5          0.6754       0.6756     raw
#     btts              0.6833       0.6832     calibrated
#
# Applying it everywhere would make match result worse. "Calibrated: true" in
# the metadata means calibrators were *fitted*, not that they were an
# improvement on every target.
USE_CALIBRATOR = {"match_result": False, "over_1_5": True, "over_2_5": False}


def _apply_calibrator(spec: dict | None, target: str, probs: list[float]) -> list[float]:
    """Apply the isotonic calibrators saved at training time.

    `spec` is the entry from calibrators.joblib: {classes, weights,
    calibrators}, where `calibrators` is one IsotonicRegression per class.
    """
    if not spec or not USE_CALIBRATOR.get(target, False):
        return probs
    cals = spec.get("calibrators")
    if not isinstance(cals, (list, tuple)) or len(cals) != len(probs):
        return probs
    try:
        out = [float(c.predict([p])[0]) for c, p in zip(cals, probs)]
        total = sum(out)
        # Isotonic is per-class and does not preserve the sum, so renormalise
        # or a three-way market stops being a probability distribution.
        return [o / total for o in out] if total > 0 else probs
    except Exception:
        return probs


def predict_fixture(fixture: dict, index) -> dict | None:
    """Ensemble probabilities for one fixture, or None when unavailable."""
    state = _load()
    if not state.get("models"):
        return None

    if REQUIRE_MARKET and not ((fixture.get("odds") or {}).get("implied")):
        return None

    feats = build_features(fixture, index)
    if feats is None:
        return None

    try:
        import numpy as np
        X = np.array([feats], dtype=float)
    except Exception:
        return None

    out: dict = {}
    for target, family_models in state["models"].items():
        spec = state["calibrators"].get(target) or {}
        # The ensemble weights fitted at training time. They cover six families
        # including the two we do not load, so they are renormalised over the
        # families actually present rather than summing to less than one.
        trained_w = spec.get("weights") or {}

        preds, wts = [], []
        for fam, model in family_models:
            try:
                p = model.predict_proba(X)[0]
            except Exception:
                continue
            preds.append([float(x) for x in p])
            wts.append(float(trained_w.get(fam, 1.0)))
        if not preds:
            continue

        total_w = sum(wts) or float(len(preds))
        blended = [
            sum(p[i] * w for p, w in zip(preds, wts)) / total_w
            for i in range(len(preds[0]))
        ]
        out[target] = _apply_calibrator(spec, target, blended)

    if not out:
        return None

    result: dict = {"families": len(FAMILIES)}

    if "match_result" in out:
        # meta stores this as {"0": "Away Win", "1": "Draw", "2": "Home Win"} —
        # a dict, so iterating it yields the *keys*. Zipping the raw value put
        # the probabilities under "0"/"1"/"2" and left home_win reading as
        # zero on every fixture.
        raw_classes = (state["meta"] or {}).get("result_classes")
        if isinstance(raw_classes, dict):
            labels = [raw_classes[k] for k in sorted(raw_classes, key=int)]
        elif isinstance(raw_classes, (list, tuple)):
            labels = list(raw_classes)
        else:
            labels = ["Away Win", "Draw", "Home Win"]
        key_for = {"away win": "away_win", "draw": "draw", "home win": "home_win"}
        for label, p in zip(labels, out["match_result"]):
            result[key_for.get(str(label).strip().lower(),
                               str(label).strip().lower().replace(" ", "_"))] = round(float(p), 4)

    for target in ("over_1_5", "over_2_5"):
        if target in out:
            result[target] = round(float(out[target][1]), 4)
    return result


# How a published market maps onto what the ensemble predicts. Markets absent
# here (Under 3.5, BTTS) simply get no second opinion.
def market_probability(ml: dict | None, market: str) -> float | None:
    """The ensemble's probability for one published market, if it has one."""
    if not ml:
        return None
    direct = ml.get(market)
    if direct is not None:
        return float(direct)
    if market == "under_2_5" and ml.get("over_2_5") is not None:
        return 1.0 - float(ml["over_2_5"])
    if market == "home_or_draw" and ml.get("home_win") is not None:
        return float(ml["home_win"]) + float(ml.get("draw") or 0.0)
    if market == "away_or_draw" and ml.get("away_win") is not None:
        return float(ml["away_win"]) + float(ml.get("draw") or 0.0)
    return None


def status() -> dict:
    state = _load()
    meta = state.get("meta") or {}
    return {
        "available": bool(state.get("models")),
        "targets": sorted(state.get("models", {}).keys()),
        "families_per_target": {t: [f for f, _ in m] for t, m in state.get("models", {}).items()},
        "trained_at": meta.get("trained_at"),
        "n_samples": meta.get("n_samples"),
        "n_features": len(meta.get("feature_columns") or []),
        "calibrated": bool(state.get("calibrators")),
    }
