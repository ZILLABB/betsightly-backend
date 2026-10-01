"""Capture one read-only, pre-kickoff fixture/price board for offline shadow work.

This does not run the publication pipeline or create booking codes. The output
path must be outside the repository and is never a published-card table.
"""

import argparse
import copy
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests


def model_fingerprint() -> str:
    root = Path(__file__).resolve().parents[1] / "models" / "api_football"
    digest = hashlib.sha256()
    for path in sorted(root.glob("*.joblib")) + sorted(root.glob("*.json")):
        digest.update(path.name.encode("utf-8"))
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def capture(output: Path, days: int = 4, *, complete: bool = False) -> dict:
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"
    from leagues import espn_source, sportybet

    frozen_history = None
    if complete:
        from leagues import base_rates, elo_engine, ml_models, team_history
        from leagues.espn_source import ESPN_CLUB_LEAGUES
        from leagues.picks import (MIN_CANDIDATE_CONFIDENCE,
                                   MIN_PUBLISHABLE_CONFIDENCE)
        from leagues import selection
        rates = base_rates.compute_base_rates(ESPN_CLUB_LEAGUES)
        history_data = team_history.build(ESPN_CLUB_LEAGUES)
        ratings = elo_engine.get_ratings(ESPN_CLUB_LEAGUES)
        if rates.get("_failed_leagues") or history_data.get("failed_leagues"):
            raise ValueError("complete capture requires complete historical inputs")
        frozen_history = {
            "base_rates": rates, "team_history": history_data,
            "elo_ratings": ratings,
            "elo_cache_observed_at": datetime.now(timezone.utc).isoformat(),
            "selection_policy": {
                "min_candidate_confidence": MIN_CANDIDATE_CONFIDENCE,
                "min_publishable_confidence": MIN_PUBLISHABLE_CONFIDENCE,
                "min_useful_odds": selection.MIN_USEFUL_ODDS,
                "market_cap": selection.MARKET_CAP,
                "team_to_score_cap": selection.TEAM_TO_SCORE_CAP,
                "under_cap": selection.UNDER_CAP,
                "per_band": selection._PER_BAND,
                "per_band_group": selection._PER_BAND_GROUP,
                "max_search_candidates": selection._MAX_SEARCH_CANDIDATES,
                "price_bands": selection._PRICE_BANDS,
            },
        }

    started = datetime.now(timezone.utc)
    calibration_response = requests.get(
        "https://betsightly-api.onrender.com/api/leagues/calibration-fit",
        timeout=25,
    )
    calibration_response.raise_for_status()
    calibration = calibration_response.json()
    if calibration.get("status") != "success" or not isinstance(
            calibration.get("groups"), dict):
        raise ValueError("production calibration snapshot unavailable")
    calibration_observed_at = datetime.now(timezone.utc).isoformat()
    fixtures = espn_source.get_fixtures(days_ahead=days, force=False,
                                         now=started)
    provider = espn_source.cache_metadata()
    # Prevent SportyBet's normal database-backed cache from reading or writing
    # any database. Only its public upcoming-board GET is used.
    sportybet._db_get = lambda *_args, **_kwargs: None
    sportybet._db_set = lambda *_args, **_kwargs: None
    board = sportybet.fetch_board(force=True)
    fixtures = copy.deepcopy(fixtures)
    matched = sportybet.apply_to_fixtures(fixtures, board=board)
    captured_at = datetime.now(timezone.utc)
    cutoff = captured_at + timedelta(minutes=30)
    fixtures = [fixture for fixture in fixtures if datetime.fromisoformat(
        fixture["commence_time"].replace("Z", "+00:00")) > cutoff]
    fixtures.sort(key=lambda f: (f["commence_time"], f["match_id"]))
    payload = {
        "schema": 2 if complete else 1,
        "captured_at": captured_at.isoformat(),
        "minimum_kickoff": cutoff.isoformat(),
        "provider": provider,
        "calibration": calibration,
        "calibration_observed_at": calibration_observed_at,
        "model_fingerprint": model_fingerprint(),
        "sportybet": sportybet.board_metadata(board),
        "sportybet_matched_before_kickoff_filter": matched,
        "fixtures": fixtures,
    }
    if complete:
        from leagues import base_rates, ml_models, team_history
        from leagues.engine import _elo_for
        from leagues.predictor import predict
        from leagues.espn_source import ESPN_CLUB_LEAGUES
        index = team_history.HistoryIndex(frozen_history["team_history"])
        model_inputs = {}
        for fixture in fixtures:
            base = base_rates.rates_for(fixture["league_slug"],
                                        frozen_history["base_rates"])
            elo = _elo_for(fixture, frozen_history["elo_ratings"])
            model = predict(fixture, base, elo)
            model_inputs[fixture["match_id"]] = {
                "base": base, "elo": elo,
                "ml_features": ml_models.build_features(fixture, index),
                "ml_output": ml_models.predict_fixture(fixture, index),
                "raw_model": model,
                "home_history_count": len(index.by_team.get((
                    fixture.get("team_type") or "CLUB", fixture["home"]["name"])) or []),
                "away_history_count": len(index.by_team.get((
                    fixture.get("team_type") or "CLUB", fixture["away"]["name"])) or []),
                "h2h_count": len(index.h2h.get((
                    fixture.get("team_type") or "CLUB",
                    *sorted((fixture["home"]["name"], fixture["away"]["name"]))
                )) or []),
            }
        payload["historical_inputs"] = frozen_history
        payload["model_inputs"] = model_inputs
        payload["sportybet_board"] = board
        payload["target_wat_date"] = (
            captured_at.astimezone(timezone(timedelta(hours=1))).date()
            + timedelta(days=1)).isoformat()
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False).encode("utf-8")
    payload["snapshot_id"] = hashlib.sha256(raw).hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return {
        "snapshot_id": payload["snapshot_id"],
        "captured_at": payload["captured_at"],
        "fixtures": len(fixtures),
        "priced": sum(bool((f.get("odds") or {}).get("implied")) for f in fixtures),
        "sportybet_matched": sum(bool((f.get("odds") or {}).get("sportybet_event_id"))
                                 for f in fixtures),
        "provider_success": provider.get("successful_league_count"),
        "provider_failed": provider.get("failed_league_count"),
        "output": str(output),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--days", type=int, default=4)
    parser.add_argument("--complete", action="store_true")
    arguments = parser.parse_args()
    print(json.dumps(capture(arguments.output, arguments.days,
                             complete=arguments.complete), sort_keys=True))
