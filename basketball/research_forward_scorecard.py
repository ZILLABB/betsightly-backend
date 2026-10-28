"""Private forward scorecard for ORIGINAL NBA predictions, not bookmaker ROI.

Read-only, uses the signed research archive and independently verified finals.
No refitting, post-tipoff prediction generation or model promotion.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from math import isfinite, log, sqrt
from basketball.research_private_bundle import inspect_bundle

MIN_INDEPENDENT_FORWARD_GAMES = 100
PREGAME_BUFFER = timedelta(minutes=10)


def _clock(v):
    d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    if d.tzinfo is None or d.utcoffset() is None:
        raise ValueError("NBA_SCORECARD_CLOCK_MUST_BE_AWARE")
    return d.astimezone(timezone.utc)


def _num(v):
    if isinstance(v, bool) or not isinstance(v, (float, int)) or not isfinite(v):
        raise ValueError("NBA_SCORECARD_NONFINITE_VALUE")
    return float(v)


def scorecard(archive):
    """Require immutable record and original timestamps for every scored game."""
    inspect_bundle(archive)
    fixture = {str(g["game_id"]): g for g in archive["fixtures"]}
    records = archive["records"]
    verified = {
        name: {str(row["game_id"]): row for row in records[key]}
        for name, key in (("moneyline", "moneyline_finals"),
                          ("opening_score", "opening_score_finals"))
    }
    by_model = {}
    for model, key in (("moneyline", "moneyline"),
                       ("opening_score", "opening_score")):
        rows = []
        for prediction in records[key]:
            gid = str(prediction["game_id"])
            game, final = fixture[gid], verified[model].get(gid)
            if final is None or game["status"] != "final":
                continue
            kickoff = _clock(game["start_utc"])
            captured = _clock(prediction["captured_at"])
            if captured + PREGAME_BUFFER >= kickoff:
                raise ValueError("NBA_SCORECARD_PREGAME_LEAKAGE")
            if (int(game["home_score"]) != int(final["home_score"]) or
                    int(game["away_score"]) != int(final["away_score"])):
                raise ValueError("NBA_SCORECARD_FINAL_MISMATCH")
            home = int(final["home_score"]); away = int(final["away_score"])
            if model == "moneyline":
                p = _num(prediction["probability_home_win"])
                if not 0 < p < 1:
                    raise ValueError("NBA_SCORECARD_PROBABILITY_INVALID")
                outcome = float(home > away)
                brier = (p - outcome) ** 2
                loss = -(outcome * log(p) + (1-outcome) * log(1-p))
                rows.append((brier, loss, float(int(p >= 0.5) == int(outcome))))
            else:
                h = _num(prediction["predicted_home_points"])
                a = _num(prediction["predicted_away_points"])
                rows.append((abs(h-home), abs(a-away),
                             abs((h+a)-(home+away))))
        n = len(rows)
        if model == "moneyline":
            metrics = {"brier": round(sum(x[0] for x in rows)/n, 5) if n else None,
                       "log_loss": round(sum(x[1] for x in rows)/n, 5) if n else None,
                       "accuracy": round(sum(x[2] for x in rows)/n, 5) if n else None}
        else:
            metrics = {"home_mae": round(sum(x[0] for x in rows)/n, 4) if n else None,
                       "away_mae": round(sum(x[1] for x in rows)/n, 4) if n else None,
                       "total_mae": round(sum(x[2] for x in rows)/n, 4) if n else None}
        by_model[model] = {"verified_forward_games": n, **metrics,
                           "minimum_required": MIN_INDEPENDENT_FORWARD_GAMES,
                           "independent_release_validated":
                               n >= MIN_INDEPENDENT_FORWARD_GAMES}
    return {
        "status": "research_only",
        "models": by_model,
        "eligible_for_public_prediction":
            all(m["independent_release_validated"] for m in by_model.values())
            and False,  # Additional calibration, rights and price gates.
        "no_model_refit": True, "no_bookmaker_prices": True,
        "betting_roi": None, "not_bookable": True,
    }
