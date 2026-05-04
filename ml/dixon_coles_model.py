"""
Dixon-Coles / Poisson Regression model for football prediction.
The 1997 gold standard: models goals as Poisson processes per team with
attack/defence ratings, home advantage, and low-score correction (rho).
"""
from __future__ import annotations
import logging
import numpy as np
from typing import Dict, Any, List, Tuple
from scipy.optimize import minimize
from scipy.stats import poisson

logger = logging.getLogger(__name__)


class DixonColesModel:
    def __init__(self, xi=0.0018):
        self.xi = xi
        self.attack: Dict[str, float] = {}
        self.defence: Dict[str, float] = {}
        self.home_advantage = 0.0
        self.rho = 0.0
        self.is_trained = False
        self.teams: List[str] = []

    def train(self, matches):
        if len(matches) < 20:
            logger.warning("Dixon-Coles needs at least 20 matches to fit reliably")
        self.teams = sorted(set([m["home_team"] for m in matches] + [m["away_team"] for m in matches]))
        n = len(self.teams)
        idx = {t: i for i, t in enumerate(self.teams)}
        weights = self._time_weights(matches)
        x0 = np.zeros(n * 2 + 2)
        x0[:n] = 0.5; x0[n:2*n] = 0.5; x0[-2] = 0.3; x0[-1] = -0.1
        result = minimize(self._nll, x0, args=(matches, idx, weights), method="L-BFGS-B",
                          options={"maxiter": 500, "ftol": 1e-9})
        params = result.x
        for team, i in idx.items():
            self.attack[team] = np.exp(params[i])
            self.defence[team] = np.exp(params[n + i])
        self.home_advantage = np.exp(params[-2])
        self.rho = params[-1]
        self.is_trained = True
        logger.info(f"Dixon-Coles trained on {len(matches)} matches, {n} teams")

    def _time_weights(self, matches):
        from datetime import datetime
        dates = []
        for m in matches:
            try:
                dates.append(datetime.fromisoformat(str(m["date"]).split("T")[0]))
            except Exception:
                dates.append(datetime.now())
        latest = max(dates) if dates else datetime.now()
        return np.array([np.exp(-self.xi * max((latest - d).days, 0)) for d in dates])

    def _nll(self, params, matches, idx, weights):
        n = len(idx)
        att = np.exp(params[:n]); deff = np.exp(params[n:2*n])
        ha = np.exp(params[-2]); rho = params[-1]
        ll = 0.0
        for i, m in enumerate(matches):
            hi = idx.get(m["home_team"]); ai = idx.get(m["away_team"])
            if hi is None or ai is None: continue
            mu_h = att[hi] * deff[ai] * ha; mu_a = att[ai] * deff[hi]
            hg, ag = int(m["home_goals"]), int(m["away_goals"])
            ll += weights[i] * (poisson.logpmf(hg, mu_h) + poisson.logpmf(ag, mu_a)
                                + np.log(max(self._tau(hg, ag, mu_h, mu_a, rho), 1e-10)))
        return -ll

    @staticmethod
    def _tau(hg, ag, mu_h, mu_a, rho):
        if hg == 0 and ag == 0: return 1 - mu_h * mu_a * rho
        elif hg == 0 and ag == 1: return 1 + mu_h * rho
        elif hg == 1 and ag == 0: return 1 + mu_a * rho
        elif hg == 1 and ag == 1: return 1 - rho
        return 1.0

    def _lambdas(self, home, away):
        mu_h = self.attack.get(home, 1.0) * self.defence.get(away, 1.0) * self.home_advantage
        mu_a = self.attack.get(away, 1.0) * self.defence.get(home, 1.0)
        return mu_h, mu_a

    def predict_score_matrix(self, home, away, max_goals=8):
        mu_h, mu_a = self._lambdas(home, away)
        m = np.outer(poisson.pmf(range(max_goals+1), mu_h), poisson.pmf(range(max_goals+1), mu_a))
        for hg in range(2):
            for ag in range(2):
                m[hg, ag] *= self._tau(hg, ag, mu_h, mu_a, self.rho)
        return m / m.sum()

    def predict(self, home_team, away_team):
        if not self.is_trained:
            return {"prediction": "home_win", "confidence": 0.4,
                    "probabilities": {"home_win": 0.4, "draw": 0.28, "away_win": 0.32},
                    "model_name": "dixon_coles", "model_type": "dixon_coles_poisson", "note": "not trained"}
        m = self.predict_score_matrix(home_team, away_team)
        hw = float(np.tril(m, -1).sum()); draw = float(np.trace(m)); aw = float(np.triu(m, 1).sum())
        best = max([("home_win", hw), ("draw", draw), ("away_win", aw)], key=lambda x: x[1])
        mu_h, mu_a = self._lambdas(home_team, away_team)
        return {
            "prediction": best[0], "confidence": round(best[1], 4),
            "probabilities": {"home_win": round(hw, 4), "draw": round(draw, 4), "away_win": round(aw, 4)},
            "expected_home_goals": round(mu_h, 2), "expected_away_goals": round(mu_a, 2),
            "expected_total_goals": round(mu_h + mu_a, 2),
            "over_2_5_probability": round(float(1 - poisson.cdf(2, mu_h + mu_a)), 4),
            "btts_probability": round(float((1 - poisson.pmf(0, mu_h)) * (1 - poisson.pmf(0, mu_a))), 4),
            "model_name": "dixon_coles", "model_type": "dixon_coles_poisson",
        }

    def save(self, path):
        import json, os
        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
        with open(path, "w") as f:
            json.dump({"attack": self.attack, "defence": self.defence,
                       "home_advantage": self.home_advantage, "rho": self.rho,
                       "xi": self.xi, "teams": self.teams, "is_trained": self.is_trained}, f)

    def load(self, path):
        import json
        with open(path) as f:
            d = json.load(f)
        self.attack = d["attack"]; self.defence = d["defence"]
        self.home_advantage = d["home_advantage"]; self.rho = d["rho"]
        self.xi = d.get("xi", self.xi); self.teams = d.get("teams", []); self.is_trained = True
