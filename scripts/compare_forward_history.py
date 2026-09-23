"""Offline control/fixed comparison on one frozen, unstarted fixture board.

No database writes, published cards, booking calls, or settlement. This is a
research shadow; local empty calibration and shared no-Elo state are labelled.
"""

import argparse
import copy
import hashlib
import json
import os
import time
import threading
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import requests


def _verified_board(path):
    board = json.loads(path.read_text(encoding="utf-8"))
    identity = board.pop("snapshot_id")
    raw = json.dumps(board, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False).encode("utf-8")
    if hashlib.sha256(raw).hexdigest() != identity:
        raise ValueError("frozen board hash mismatch")
    board["snapshot_id"] = identity
    cutoff = datetime.fromisoformat(board["captured_at"])
    if cutoff.tzinfo is None:
        raise ValueError("capture time must be timezone-aware")
    for fixture in board["fixtures"]:
        kickoff = datetime.fromisoformat(
            fixture["commence_time"].replace("Z", "+00:00"))
        if kickoff <= cutoff:
            raise ValueError("frozen board contains started fixture")
    return board


def _run_path(fixtures, rates, history, fit):
    from leagues.base_rates import rates_for
    from leagues.fixture_ranker import canonical_fixture_recommendations
    from leagues.ml_models import predict_fixture
    from leagues.picks import MIN_CANDIDATE_CONFIDENCE, build_picks
    from leagues.predictor import predict

    candidates = []
    models = {}
    base_counts = Counter()
    history_counts = Counter()
    for frozen in fixtures:
        fixture = copy.deepcopy(frozen)
        base = rates_for(fixture["league_slug"], rates)
        fixture["competition_historical_sample"] = int(base.get("matches") or 0)
        fixture["base_rate_source"] = base.get("base_rate_source", "global_default")
        base_counts[fixture["base_rate_source"]] += 1
        home = fixture["home"]["name"]
        away = fixture["away"]["name"]
        team_type = fixture.get("team_type") or "CLUB"
        history_counts["home"] += bool(history.by_team.get((team_type, home)))
        history_counts["away"] += bool(history.by_team.get((team_type, away)))
        history_counts["h2h"] += bool(history.h2h.get((team_type, *sorted((home, away)))))
        model = predict(fixture, base, None)  # Elo held identically absent in both arms.
        model["ml"] = predict_fixture(fixture, history)
        history_counts["ml"] += bool(model["ml"])
        fixture["_model"] = model
        models[fixture["match_id"]] = {"model": model, "base": base,
                                       "fixture": fixture}
        candidates.extend(build_picks(
            fixture, model, min_confidence=MIN_CANDIDATE_CONFIDENCE, fit=fit))
    canonical = canonical_fixture_recommendations(candidates)
    return {"models": models, "candidates": candidates,
            "canonical": canonical, "base_counts": dict(base_counts),
            "history_counts": dict(history_counts)}


def _card(picks, target, max_legs, floor, min_return, safe=False):
    from leagues.selection import select_accumulator
    eligible = [p for p in picks if p.get("safe_tier_eligible")] if safe else picks
    legs, odds, joint = select_accumulator(
        eligible, target, max_legs, floor, min_ev=min_return,
        band_low=.92 if safe else .80, canonicalize=False)
    return {"odds": odds, "joint": joint, "expected_payout_factor": odds * joint,
            "legs": [{"fixture_id": p["match_id"], "market": p["market"],
                      "probability": p["confidence"], "odds": p["odds"],
                      "base_rate_source": p["_fixture"].get("base_rate_source")}
                     for p in legs]}


def _summary(path, target_date):
    candidates = path["candidates"]
    canonical = path["canonical"]
    from leagues.engine import kickoff_wat_date
    from leagues.picks import MIN_PUBLISHABLE_CONFIDENCE
    from leagues.selection import select_banker
    selected_date = target_date
    day = [p for p in canonical if kickoff_wat_date(
        p["_fixture"].get("commence_time")) == selected_date]
    banker = select_banker(
        [p for p in day if p.get("safe_tier_eligible")],
        canonicalize=False)
    banker_card = {"odds": banker[1], "joint": banker[2],
                   "legs": [{"fixture_id": p["match_id"], "market": p["market"]}
                            for p in banker[0]]}
    return {
        "base_sources": path["base_counts"],
        "history_coverage": path["history_counts"],
        "candidate_count": len(candidates),
        "safe_tier_eligible": sum(bool(p.get("safe_tier_eligible")) for p in candidates),
        "real_price": sum(bool(p.get("odds_are_real")) for p in candidates),
        "estimated_price": sum(not p.get("odds_are_real") for p in candidates),
        "bookable": sum(bool(p.get("bookable")) for p in candidates),
        "canonical_count": len(canonical),
        "market_mix": dict(Counter(p["market"] for p in canonical)),
        "selected_wat_date": selected_date,
        "selected_date_canonical_count": len(day),
        "cards": {
            "banker": banker_card,
            "2_odds": _card(day, 2, 4, MIN_PUBLISHABLE_CONFIDENCE, .82, True),
            "5_odds": _card(day, 5, 8, MIN_PUBLISHABLE_CONFIDENCE, .72),
            "10_odds": _card(day, 10, 10, MIN_PUBLISHABLE_CONFIDENCE, .63),
            "over_1_5_singles": {"legs": [
                {"fixture_id": p["match_id"], "market": p["market"],
                 "probability": p["confidence"], "odds": p["odds"]}
                for p in sorted(day, key=lambda p: -p["confidence"])
                if p["market"] == "over_1_5" and p["confidence"] >= .65
            ][:10]},
        },
    }


def _forward_records(path, board, fit, history):
    """Immutable, pre-kickoff model forecasts; never inferred from outcomes."""
    from leagues.calibrator import calibrate
    from leagues.ml_models import market_probability
    from leagues.picks import CALIBRATION_GROUP
    from leagues.predictor import predict

    created = datetime.now(timezone.utc)
    candidates = {(p["match_id"], p["market"]): p for p in path["candidates"]}
    sporty_at = datetime.fromtimestamp(
        float((board.get("sportybet") or {}).get("fetched_at") or 0),
        timezone.utc).isoformat()
    records = []
    for fixture_id, evaluated in path["models"].items():
        fixture = evaluated["fixture"]
        kickoff = datetime.fromisoformat(
            fixture["commence_time"].replace("Z", "+00:00"))
        if created >= kickoff:
            continue
        no_market = copy.deepcopy(fixture)
        no_market["odds"] = {}
        league = predict(no_market, evaluated["base"], None)
        model = evaluated["model"]
        odds = fixture.get("odds") or {}
        implied = odds.get("implied") or {}
        home = fixture["home"]["name"]
        away = fixture["away"]["name"]
        kind = fixture.get("team_type") or "CLUB"
        home_n = len(history.by_team.get((kind, home)) or [])
        away_n = len(history.by_team.get((kind, away)) or [])
        h2h_n = len(history.h2h.get((kind, *sorted((home, away)))) or [])
        for market, raw in model["probabilities"].items():
            picked = candidates.get((fixture_id, market))
            variants = {
                "devigged_bookmaker": implied.get(market),
                "league_base_rate": league["probabilities"].get(market),
                "poisson_raw": raw,
                "poisson_calibrated": calibrate(raw, CALIBRATION_GROUP[market], fit),
                "trained_ml": market_probability(model.get("ml"), market),
                "production_hybrid": picked.get("confidence") if picked else None,
            }
            quote = odds.get(market)
            for variant, probability in variants.items():
                records.append({
                    "snapshot_id": board["snapshot_id"],
                    "fixture_id": fixture_id, "market": market,
                    "model": variant,
                    "model_version": board["model_fingerprint"],
                    "predicted_at": created.isoformat(),
                    "kickoff_at": kickoff.isoformat(),
                    "probability": probability,
                    "abstain": probability is None,
                    "odds_provider": odds.get("provider") if quote else None,
                    "observed_odds": quote if isinstance(quote, (int, float)) else None,
                    "odds_observed_at": (sporty_at if odds.get("provider") == "SportyBet"
                                         else board["provider"].get("generated_at")) if quote else None,
                    "competition_type": fixture.get("competition_type"),
                    "competition_sample": int(evaluated["base"].get("matches") or 0),
                    "base_rate_source": evaluated["base"].get("base_rate_source"),
                    "home_team": home, "away_team": away,
                    "team_type": kind,
                    "home_history_count": home_n,
                    "away_history_count": away_n,
                    "h2h_count": h2h_n,
                    "calibration_version": (fit.get("policy") or {}).get("version"),
                    "calibration_sample": fit.get("n"),
                })
    return records


def compare(board_path: Path, output: Path):
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"
    from leagues import base_rates, team_history
    from leagues.espn_source import ESPN_CLUB_LEAGUES

    board = _verified_board(board_path)
    from scripts.capture_forward_board import model_fingerprint
    if board.get("model_fingerprint") != model_fingerprint():
        raise ValueError("model artifacts changed since board capture")
    calibration = board.get("calibration") or {}
    if calibration.get("status") != "success":
        raise ValueError("frozen production calibration snapshot missing")
    fit = {"n": calibration.get("n_legs", 0),
           "groups": calibration.get("groups") or {},
           "global": calibration.get("global_shift", 0),
           "policy": calibration.get("policy") or {}}
    target_date = (datetime.fromisoformat(board["captured_at"]).astimezone(
        timezone(timedelta(hours=1))).date() + timedelta(days=1)).isoformat()
    count = {"requests": 0}
    count_lock = threading.Lock()
    original_get = requests.get

    def counted_get(*args, **kwargs):
        with count_lock:
            count["requests"] += 1
        return original_get(*args, **kwargs)

    with patch("leagues.espn_history_fetch.requests.get", side_effect=counted_get):
        t0 = time.monotonic()
        fixed_rates = base_rates.compute_base_rates(ESPN_CLUB_LEAGUES)
        base_seconds = time.monotonic() - t0
        base_requests = count["requests"]
        t0 = time.monotonic()
        history_data = team_history.build(ESPN_CLUB_LEAGUES)
        history_seconds = time.monotonic() - t0
        history_requests = count["requests"] - base_requests
    fixed_history = team_history.HistoryIndex(history_data)
    control_history = team_history.HistoryIndex({"matches": []})
    control = _run_path(board["fixtures"], {}, control_history, fit)
    fixed = _run_path(board["fixtures"], fixed_rates, fixed_history, fit)
    records = _forward_records(fixed, board, fit, fixed_history)
    old = {(p["match_id"], p["market"]): p for p in control["canonical"]}
    new = {(p["match_id"], p["market"]): p for p in fixed["canonical"]}
    changes = []
    for key in sorted(set(old) | set(new)):
        a, b = old.get(key), new.get(key)
        if a is None or b is None or abs(a["confidence"] - b["confidence"]) >= .01:
            pick = b or a
            changes.append({
                "fixture_id": key[0], "fixture": (
                    f"{pick['_fixture']['home']['name']} v "
                    f"{pick['_fixture']['away']['name']}"),
                "market": key[1],
                "control_probability": a.get("confidence") if a else None,
                "fixed_probability": b.get("confidence") if b else None,
                "control_rank": a.get("public_rank") if a else None,
                "fixed_rank": b.get("public_rank") if b else None,
            })
    result = {
        "schema": 1, "snapshot_id": board["snapshot_id"],
        "captured_at": board["captured_at"], "fixture_count": len(board["fixtures"]),
        "limitations": ["Elo identically omitted",
                        "research shadow, not published cards"],
        "calibration_observed_at": board["calibration_observed_at"],
        "calibration_sample": fit["n"],
        "model_fingerprint": board["model_fingerprint"],
        "base_seconds": round(base_seconds, 2),
        "history_seconds": round(history_seconds, 2),
        "base_requests": base_requests,
        "history_requests": history_requests,
        "base_failed_leagues": fixed_rates.get("_failed_leagues") or [],
        "history_failed_leagues": history_data.get("failed_leagues") or [],
        "fixed_base_leagues": sum(bool(v.get("matches")) for k, v in fixed_rates.items()
                                  if not k.startswith("_")),
        "fixed_history_matches": sum(len(v) for v in fixed_history.h2h.values()),
        "target_wat_date": target_date,
        "control": _summary(control, target_date),
        "fixed": _summary(fixed, target_date),
        "changed_canonical": changes,
        "shadow_record_count": len(records),
        "shadow_records": records,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2,
                  allow_nan=False)
    return {k: result[k] for k in ("snapshot_id", "fixture_count",
                                    "base_seconds", "history_seconds",
                                    "base_requests", "history_requests",
                                    "fixed_base_leagues", "fixed_history_matches",
                                    "shadow_record_count")}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("board", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(compare(args.board, args.output), sort_keys=True))
