"""
Prediction Results Service — the accountability loop for the main ML pipeline.

Once a day this scores yesterday's stored predictions against real final
scores, so we can answer "how accurate were we?" with data instead of vibes.

Design goals:
  - ZERO polling. One call per day to football-data.org (free tier already
    returns final scores), covering a small date window. Rate limits never bite.
  - Pure-additive. Never mutates DailyPrediction; writes to its own table.
  - Per-market truth. Records won/lost for each market we predict
    (match_result, over_1_5, over_2_5, btts), which powers both the public
    accuracy page and (later) calibration monitoring.

Results source priority:
  1. football-data.org /matches?dateFrom..dateTo  (FREE, ~12 leagues + WC)
  2. The Odds API /scores                          (fallback, 3 days back)
"""

import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta, date as date_cls
from typing import Any, Dict, List, Optional

import requests
from sqlalchemy import Column, Integer, String, Float, Date, DateTime, Text, func

from database import Base, engine, SessionLocal
from services.team_name_resolver import TeamNameResolver

logger = logging.getLogger(__name__)

FOOTBALL_DATA_KEY = os.getenv("FOOTBALL_DATA_KEY", "")
FOOTBALL_DATA_URL = "https://api.football-data.org/v4"
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
ODDS_BASE_URL = "https://api.the-odds-api.com/v4"

# Markets we score, and how to grade them from a final score.
MARKETS = ("match_result", "over_1_5", "over_2_5", "btts")


class PredictionOutcome(Base):
    """One row per (date, fixture, market) — what we predicted vs what happened."""
    __tablename__ = "prediction_outcomes"

    id = Column(Integer, primary_key=True, index=True)
    prediction_date = Column(Date, nullable=False, index=True)
    fixture_id = Column(Integer, nullable=False, index=True)
    home_team = Column(String(255), nullable=False)
    away_team = Column(String(255), nullable=False)
    league_name = Column(String(255), default="")

    market = Column(String(40), nullable=False)       # match_result / over_1_5 / ...
    predicted = Column(String(40), nullable=False)     # home_win / over_2_5 / yes ...
    confidence = Column(Float, default=0.0)

    home_score = Column(Integer, nullable=True)
    away_score = Column(Integer, nullable=True)
    outcome = Column(String(20), default="pending")    # won / lost / void / pending

    settled_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class PredictionResultsService:
    """Scores stored daily predictions against real results."""

    def __init__(self):
        self.resolver = TeamNameResolver()
        Base.metadata.create_all(bind=engine)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def settle_date(self, target_date: Optional[str] = None) -> Dict[str, Any]:
        """Score all predictions for a date (default: yesterday).

        Returns a summary of how many picks were settled.
        """
        if target_date is None:
            target_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        d = datetime.strptime(target_date, "%Y-%m-%d").date()

        scores = self._fetch_final_scores(target_date)
        if not scores:
            logger.info(f"Results: no finished matches found for {target_date}")
            return {"date": target_date, "settled": 0, "reason": "no finished scores"}

        from services.daily_predictions_service import DailyPrediction

        db = SessionLocal()
        try:
            preds = db.query(DailyPrediction).filter(
                DailyPrediction.prediction_date == d
            ).all()
            if not preds:
                return {"date": target_date, "settled": 0, "reason": "no predictions stored"}

            settled = skipped = 0
            for p in preds:
                score = self._match_score(p.home_team, p.away_team, scores)
                if score is None:
                    skipped += 1
                    continue
                hs, as_ = score
                headline = self._extract_headline_predictions(p.ml_predictions)
                for market, (predicted, conf) in headline.items():
                    outcome = self._grade(market, predicted, hs, as_)
                    self._upsert_outcome(db, p, market, predicted, conf, hs, as_, outcome)
                    settled += 1
            db.commit()
            result = {"date": target_date, "settled": settled,
                      "fixtures_unmatched": skipped, "fixtures_total": len(preds)}
            logger.info(f"Results settled: {result}")
            return result
        finally:
            db.close()

    def get_accuracy(self, days: int = 30) -> Dict[str, Any]:
        """Aggregate settled outcomes over the last N days, per market."""
        cutoff = (datetime.now() - timedelta(days=days)).date()
        db = SessionLocal()
        try:
            rows = db.query(PredictionOutcome).filter(
                PredictionOutcome.prediction_date >= cutoff,
                PredictionOutcome.outcome.in_(("won", "lost")),
            ).all()

            by_market: Dict[str, Dict[str, int]] = defaultdict(lambda: {"won": 0, "lost": 0})
            for r in rows:
                by_market[r.market][r.outcome] += 1

            markets = {}
            tot_won = tot_total = 0
            for market, c in by_market.items():
                total = c["won"] + c["lost"]
                tot_won += c["won"]; tot_total += total
                markets[market] = {
                    "settled": total,
                    "won": c["won"],
                    "lost": c["lost"],
                    "accuracy": round(c["won"] / total, 4) if total else None,
                }

            return {
                "period_days": days,
                "overall": {
                    "settled": tot_total,
                    "won": tot_won,
                    "accuracy": round(tot_won / tot_total, 4) if tot_total else None,
                },
                "by_market": markets,
                "generated_at": datetime.now().isoformat(),
            }
        finally:
            db.close()

    # ------------------------------------------------------------------
    # Scoring helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _grade(market: str, predicted: str, hs: int, as_: int) -> str:
        """Grade one market against a final score. Returns won/lost/void."""
        total = hs + as_
        if market == "match_result":
            actual = "home_win" if hs > as_ else ("draw" if hs == as_ else "away_win")
            return "won" if predicted == actual else "lost"
        if market == "over_1_5":
            actual_over = total > 1
            return "won" if (predicted == "over_1_5") == actual_over else "lost"
        if market == "over_2_5":
            actual_over = total > 2
            return "won" if (predicted == "over_2_5") == actual_over else "lost"
        if market == "btts":
            actual_yes = hs > 0 and as_ > 0
            return "won" if (predicted == "yes") == actual_yes else "lost"
        return "void"

    @staticmethod
    def _extract_headline_predictions(ml_json: str) -> Dict[str, tuple]:
        """Pull one headline (prediction, confidence) per market from stored JSON.

        Prefers the calibrated ensemble / odds-implied keys when present,
        otherwise falls back to a majority vote across the per-model keys.
        Robust to both pre- and post-ensemble JSON formats.
        """
        try:
            ml = json.loads(ml_json or "{}")
        except Exception:
            return {}

        out: Dict[str, tuple] = {}

        def pick_for(market: str, valid_values: tuple):
            # match_result is keyed as "...result" (not "...match_result") in the
            # ensemble / odds-implied outputs.
            suffix = "result" if market == "match_result" else market
            # 1. Preferred single-source keys
            for key in (f"ensemble_{suffix}", f"odds_implied_{suffix}",
                        f"{market}_ensemble"):
                if key in ml and ml[key].get("prediction") in valid_values:
                    return ml[key]["prediction"], float(ml[key].get("confidence", 0))
            # 2. Majority vote across per-model keys (match_result_xgb, etc.)
            votes: Dict[str, List[float]] = defaultdict(list)
            for k, v in ml.items():
                if not isinstance(v, dict):
                    continue
                if market in k and v.get("prediction") in valid_values:
                    votes[v["prediction"]].append(float(v.get("confidence", 0)))
            # ELO / Dixon-Coles also vote on match_result
            if market == "match_result":
                for k in ("elo_rating", "dixon_coles"):
                    v = ml.get(k)
                    if isinstance(v, dict) and v.get("prediction") in valid_values:
                        votes[v["prediction"]].append(float(v.get("confidence", 0)))
            if not votes:
                return None
            winner = max(votes, key=lambda p: (len(votes[p]), sum(votes[p])))
            confs = votes[winner]
            return winner, round(sum(confs) / len(confs), 4)

        for market, values in (
            ("match_result", ("home_win", "draw", "away_win")),
            ("over_1_5", ("over_1_5", "under_1_5")),
            ("over_2_5", ("over_2_5", "under_2_5")),
            ("btts", ("yes", "no")),
        ):
            r = pick_for(market, values)
            if r:
                out[market] = r
        return out

    def _match_score(self, home: str, away: str,
                     scores: Dict[str, tuple]) -> Optional[tuple]:
        """Find the final score for a (home, away) pair using normalized names."""
        key = self._norm(home) + "|" + self._norm(away)
        if key in scores:
            return scores[key]
        # Try resolver-normalized variant (predictions store resolved names)
        rh = self.resolver.resolve(home) or home
        ra = self.resolver.resolve(away) or away
        key2 = self._norm(rh) + "|" + self._norm(ra)
        return scores.get(key2)

    @staticmethod
    def _norm(name: str) -> str:
        return (name or "").lower().strip()

    def _upsert_outcome(self, db, pred, market, predicted, conf, hs, as_, outcome):
        existing = db.query(PredictionOutcome).filter(
            PredictionOutcome.prediction_date == pred.prediction_date,
            PredictionOutcome.fixture_id == pred.fixture_id,
            PredictionOutcome.market == market,
        ).first()
        if existing:
            existing.predicted = predicted
            existing.confidence = conf
            existing.home_score = hs
            existing.away_score = as_
            existing.outcome = outcome
            existing.settled_at = datetime.utcnow()
        else:
            db.add(PredictionOutcome(
                prediction_date=pred.prediction_date,
                fixture_id=pred.fixture_id,
                home_team=pred.home_team,
                away_team=pred.away_team,
                league_name=pred.league_name,
                market=market,
                predicted=predicted,
                confidence=conf,
                home_score=hs,
                away_score=as_,
                outcome=outcome,
                settled_at=datetime.utcnow(),
            ))

    # ------------------------------------------------------------------
    # Score fetching — football-data.org first (free), Odds API fallback
    # ------------------------------------------------------------------

    def _fetch_final_scores(self, target_date: str) -> Dict[str, tuple]:
        """Return {norm_home|norm_away: (home_score, away_score)} for finished games.

        Names are resolved to training-data names so they line up with the
        names stored in DailyPrediction rows.
        """
        scores: Dict[str, tuple] = {}
        scores.update(self._scores_from_football_data(target_date))
        if not scores:
            scores.update(self._scores_from_odds_api())
        return scores

    def _scores_from_football_data(self, target_date: str) -> Dict[str, tuple]:
        if not FOOTBALL_DATA_KEY:
            return {}
        try:
            d = datetime.strptime(target_date, "%Y-%m-%d")
            params = {
                "dateFrom": target_date,
                "dateTo": (d + timedelta(days=1)).strftime("%Y-%m-%d"),
                "status": "FINISHED",
            }
            resp = requests.get(
                f"{FOOTBALL_DATA_URL}/matches",
                headers={"X-Auth-Token": FOOTBALL_DATA_KEY},
                params=params,
                timeout=20,
            )
            if resp.status_code != 200:
                logger.warning(f"football-data.org scores HTTP {resp.status_code}")
                return {}
            out: Dict[str, tuple] = {}
            for m in resp.json().get("matches", []):
                if m.get("status") != "FINISHED":
                    continue
                ft = (m.get("score") or {}).get("fullTime") or {}
                hs, as_ = ft.get("home"), ft.get("away")
                if hs is None or as_ is None:
                    continue
                home_raw = m.get("homeTeam", {}).get("name", "")
                away_raw = m.get("awayTeam", {}).get("name", "")
                home = self.resolver.resolve(home_raw) or home_raw
                away = self.resolver.resolve(away_raw) or away_raw
                out[self._norm(home) + "|" + self._norm(away)] = (int(hs), int(as_))
            logger.info(f"football-data.org: {len(out)} finished matches for {target_date}")
            return out
        except Exception as e:
            logger.error(f"football-data.org scores error: {e}")
            return {}

    def _scores_from_odds_api(self) -> Dict[str, tuple]:
        """Fallback: Odds API /scores (covers leagues football-data.org lacks)."""
        if not ODDS_API_KEY:
            return {}
        sport_keys = [
            "soccer_fifa_world_cup", "soccer_usa_mls", "soccer_brazil_campeonato",
            "soccer_argentina_primera_division", "soccer_norway_eliteserien",
            "soccer_sweden_allsvenskan",
        ]
        out: Dict[str, tuple] = {}
        for sk in sport_keys:
            try:
                resp = requests.get(
                    f"{ODDS_BASE_URL}/sports/{sk}/scores",
                    params={"apiKey": ODDS_API_KEY, "daysFrom": 3, "dateFormat": "iso"},
                    timeout=15,
                )
                if resp.status_code != 200:
                    continue
                for fx in resp.json():
                    if not fx.get("completed"):
                        continue
                    home_raw = fx.get("home_team", "")
                    away_raw = fx.get("away_team", "")
                    hs = as_ = None
                    for s in fx.get("scores") or []:
                        nm = self._norm(s.get("name", ""))
                        if nm == self._norm(home_raw):
                            hs = int(s.get("score") or 0)
                        elif nm == self._norm(away_raw):
                            as_ = int(s.get("score") or 0)
                    if hs is None or as_ is None:
                        continue
                    home = self.resolver.resolve(home_raw) or home_raw
                    away = self.resolver.resolve(away_raw) or away_raw
                    out[self._norm(home) + "|" + self._norm(away)] = (hs, as_)
            except Exception as e:
                logger.debug(f"Odds API scores {sk} failed: {e}")
        return out
