"""Leak-resistant football-only feature contract for challenger models.

This module deliberately knows nothing about bookmaker prices, implied
probabilities, market-derived expected goals, existing predictions, or betting
evidence.  Historical training and live challenger inference must both build
features through :class:`FootballHistoryState`.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date, datetime
import math
import re
import unicodedata


FEATURE_SCHEMA_VERSION = "football-first-v1"
MODEL_FAMILY = "football_first_expected_goals"

FEATURE_COLUMNS = (
    "home_win_rate_5", "home_win_rate_10", "home_draw_rate_5",
    "home_points_per_game_5", "home_goals_for_5", "home_goals_against_5",
    "home_goals_for_10", "home_goals_against_10",
    "home_venue_win_rate_5", "home_venue_goals_for_5",
    "home_venue_goals_against_5", "home_rest_days", "home_history_coverage",
    "away_win_rate_5", "away_win_rate_10", "away_draw_rate_5",
    "away_points_per_game_5", "away_goals_for_5", "away_goals_against_5",
    "away_goals_for_10", "away_goals_against_10",
    "away_venue_win_rate_5", "away_venue_goals_for_5",
    "away_venue_goals_against_5", "away_rest_days", "away_history_coverage",
    "h2h_home_win_rate", "h2h_draw_rate", "h2h_avg_goals",
    "h2h_btts_rate", "h2h_coverage",
    "league_home_win_rate", "league_draw_rate", "league_avg_goals",
    "league_over_1_5_rate", "league_over_2_5_rate", "league_btts_rate",
    "league_history_coverage", "elo_home_expected", "elo_difference_scaled",
    "elo_history_coverage", "neutral_venue", "is_cup", "is_knockout",
    "is_second_leg",
)

BOOKMAKER_FORBIDDEN_TOKENS = (
    "odds", "price", "implied", "market", "bookmaker", "sportybet",
)


def normalize_team_name(value: object) -> str:
    """Conservative name normalization; league/team-type remain part of ID."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def team_identity(league_id: object, team: object,
                  team_type: str = "CLUB") -> tuple[str, str, str]:
    normalized = normalize_team_name(team)
    if not normalized:
        raise ValueError("TEAM_IDENTITY_MISSING")
    return (str(team_type or "CLUB").upper(), str(league_id or "unknown"), normalized)


def _as_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value)[:10]).date()


@dataclass(frozen=True)
class FootballFeatureVector:
    values: tuple[float, ...]
    as_of: str
    source: str
    missing: tuple[str, ...]
    home_identity: tuple[str, str, str]
    away_identity: tuple[str, str, str]

    def as_list(self) -> list[float]:
        return list(self.values)

    def as_dict(self) -> dict[str, float]:
        return dict(zip(FEATURE_COLUMNS, self.values))


class FootballHistoryState:
    """Rolling pre-match state. Call ``features`` before ``observe`` per date."""

    def __init__(self, max_history: int = 30):
        self.max_history = max_history
        self.team_games = defaultdict(lambda: deque(maxlen=max_history))
        self.venue_games = defaultdict(lambda: deque(maxlen=max_history))
        self.h2h_games = defaultdict(lambda: deque(maxlen=10))
        self.league_games = defaultdict(lambda: deque(maxlen=1000))
        self.elo = defaultdict(lambda: 1500.0)
        self.elo_matches = defaultdict(int)

    @staticmethod
    def _rates(rows: list[dict]) -> dict[str, float]:
        if not rows:
            return {"win": .40, "draw": .27, "ppg": 1.47,
                    "gf": 1.35, "ga": 1.35}
        n = len(rows)
        wins = sum(r["gf"] > r["ga"] for r in rows)
        draws = sum(r["gf"] == r["ga"] for r in rows)
        return {
            "win": wins / n, "draw": draws / n,
            "ppg": (3 * wins + draws) / n,
            "gf": sum(r["gf"] for r in rows) / n,
            "ga": sum(r["ga"] for r in rows) / n,
        }

    @staticmethod
    def _rest(rows: list[dict], as_of: date) -> tuple[float, bool]:
        if not rows:
            return 7.0, True
        days = (as_of - rows[-1]["date"]).days
        # Negative/zero rest indicates malformed ordering. Cap long off-seasons
        # because the feature represents recovery, not calendar age.
        if days <= 0:
            raise ValueError("NON_CHRONOLOGICAL_HISTORY")
        return float(min(days, 21)), False

    def features(self, *, league_id: object, home_team: object,
                 away_team: object, as_of: object, team_type: str = "CLUB",
                 neutral_venue: bool = False, is_cup: bool = False,
                 is_knockout: bool = False, is_second_leg: bool = False,
                 source: str = "historical_results") -> FootballFeatureVector:
        match_date = _as_date(as_of)
        home = team_identity(league_id, home_team, team_type)
        away = team_identity(league_id, away_team, team_type)
        if home == away:
            raise ValueError("DUPLICATE_TEAM_IDENTITY")

        hr = list(self.team_games[home])
        ar = list(self.team_games[away])
        hv = list(self.venue_games[(home, "home")])
        av = list(self.venue_games[(away, "away")])
        h5, h10 = self._rates(hr[-5:]), self._rates(hr[-10:])
        a5, a10 = self._rates(ar[-5:]), self._rates(ar[-10:])
        hv5, av5 = self._rates(hv[-5:]), self._rates(av[-5:])
        h_rest, h_rest_missing = self._rest(hr, match_date)
        a_rest, a_rest_missing = self._rest(ar, match_date)

        pair = (home[0], home[1], *sorted((home[2], away[2])))
        h2h = list(self.h2h_games[pair])
        if h2h:
            oriented = []
            for row in h2h:
                if row["home"] == home:
                    hg, ag = row["hg"], row["ag"]
                else:
                    hg, ag = row["ag"], row["hg"]
                oriented.append((hg, ag))
            hn = len(oriented)
            h2h_values = (
                sum(hg > ag for hg, ag in oriented) / hn,
                sum(hg == ag for hg, ag in oriented) / hn,
                sum(hg + ag for hg, ag in oriented) / hn,
                sum(hg > 0 and ag > 0 for hg, ag in oriented) / hn,
                min(hn, 10) / 10.0,
            )
        else:
            h2h_values = (.40, .27, 2.70, .52, 0.0)

        league_key = (home[0], home[1])
        lr = list(self.league_games[league_key])
        if lr:
            ln = len(lr)
            league_values = (
                sum(r["hg"] > r["ag"] for r in lr) / ln,
                sum(r["hg"] == r["ag"] for r in lr) / ln,
                sum(r["hg"] + r["ag"] for r in lr) / ln,
                sum(r["hg"] + r["ag"] > 1 for r in lr) / ln,
                sum(r["hg"] + r["ag"] > 2 for r in lr) / ln,
                sum(r["hg"] > 0 and r["ag"] > 0 for r in lr) / ln,
                min(ln, 200) / 200.0,
            )
        else:
            league_values = (.44, .27, 2.70, .75, .52, .52, 0.0)

        rh, ra = self.elo[home], self.elo[away]
        advantage = 0.0 if neutral_venue else 55.0
        elo_expected = 1.0 / (1.0 + 10 ** (-(rh + advantage - ra) / 400.0))
        elo_evidence = min(self.elo_matches[home], self.elo_matches[away], 20) / 20.0

        missing = []
        if len(hr) < 5: missing.append("home_history_lt_5")
        if len(ar) < 5: missing.append("away_history_lt_5")
        if len(hv) < 3: missing.append("home_venue_history_lt_3")
        if len(av) < 3: missing.append("away_venue_history_lt_3")
        if not h2h: missing.append("h2h_missing")
        if not lr: missing.append("league_history_missing")
        if h_rest_missing: missing.append("home_rest_missing")
        if a_rest_missing: missing.append("away_rest_missing")

        values = (
            h5["win"], h10["win"], h5["draw"], h5["ppg"], h5["gf"], h5["ga"],
            h10["gf"], h10["ga"], hv5["win"], hv5["gf"], hv5["ga"], h_rest,
            min(len(hr), 10) / 10.0,
            a5["win"], a10["win"], a5["draw"], a5["ppg"], a5["gf"], a5["ga"],
            a10["gf"], a10["ga"], av5["win"], av5["gf"], av5["ga"], a_rest,
            min(len(ar), 10) / 10.0,
            *h2h_values, *league_values, elo_expected,
            max(-1.0, min(1.0, (rh - ra) / 600.0)), elo_evidence,
            float(bool(neutral_venue)), float(bool(is_cup)),
            float(bool(is_knockout)), float(bool(is_second_leg)),
        )
        if len(values) != len(FEATURE_COLUMNS) or any(not math.isfinite(v) for v in values):
            raise ValueError("INVALID_FOOTBALL_FEATURE_VECTOR")
        return FootballFeatureVector(
            tuple(float(v) for v in values), match_date.isoformat(), source,
            tuple(missing), home, away,
        )

    def observe(self, *, league_id: object, home_team: object,
                away_team: object, played_at: object, home_goals: int,
                away_goals: int, team_type: str = "CLUB") -> None:
        played = _as_date(played_at)
        home = team_identity(league_id, home_team, team_type)
        away = team_identity(league_id, away_team, team_type)
        if home == away:
            raise ValueError("DUPLICATE_TEAM_IDENTITY")
        hg, ag = int(home_goals), int(away_goals)
        if hg < 0 or ag < 0:
            raise ValueError("INVALID_SCORE")
        for identity in (home, away):
            rows = self.team_games[identity]
            if rows and played < rows[-1]["date"]:
                raise ValueError("NON_CHRONOLOGICAL_HISTORY")
        self.team_games[home].append({"date": played, "gf": hg, "ga": ag})
        self.team_games[away].append({"date": played, "gf": ag, "ga": hg})
        self.venue_games[(home, "home")].append({"date": played, "gf": hg, "ga": ag})
        self.venue_games[(away, "away")].append({"date": played, "gf": ag, "ga": hg})
        pair = (home[0], home[1], *sorted((home[2], away[2])))
        self.h2h_games[pair].append({"date": played, "home": home,
                                     "away": away, "hg": hg, "ag": ag})
        self.league_games[(home[0], home[1])].append(
            {"date": played, "hg": hg, "ag": ag}
        )

        expected = 1.0 / (1.0 + 10 ** (-(self.elo[home] + 55.0 - self.elo[away]) / 400.0))
        actual = 1.0 if hg > ag else (0.5 if hg == ag else 0.0)
        delta = 20.0 * (actual - expected)
        self.elo[home] += delta
        self.elo[away] -= delta
        self.elo_matches[home] += 1
        self.elo_matches[away] += 1


def validate_contract() -> tuple[bool, str]:
    lowered = [name.lower() for name in FEATURE_COLUMNS]
    leaked = [name for name in lowered if any(token in name for token in BOOKMAKER_FORBIDDEN_TOKENS)]
    if leaked:
        return False, f"BOOKMAKER_DERIVED_FEATURES:{','.join(leaked)}"
    if len(set(FEATURE_COLUMNS)) != len(FEATURE_COLUMNS):
        return False, "DUPLICATE_FEATURE_NAMES"
    return True, "COMPATIBLE"
