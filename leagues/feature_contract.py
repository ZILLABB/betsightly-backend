"""Single ordered, versioned feature contract for football ML.

Training, replay tooling, and live inference must call this module instead of
reimplementing feature scaling.  A model artifact is compatible only when its
metadata names this exact schema version and ordered column list.
"""
from __future__ import annotations

from dataclasses import dataclass

from leagues.market_quotes import exact_total_probability

FEATURE_SCHEMA_VERSION = "football-25-v2"
FEATURE_COLUMNS = (
    "home_win_rate_5", "home_win_rate_10", "home_draw_rate_5",
    "home_goals_scored_5", "home_goals_conceded_5",
    "home_home_win_rate_5", "home_home_goals_5",
    "away_win_rate_5", "away_win_rate_10", "away_draw_rate_5",
    "away_goals_scored_5", "away_goals_conceded_5",
    "away_away_win_rate_5", "away_away_goals_5",
    "h2h_home_win_rate", "h2h_avg_goals", "h2h_btts_rate",
    "h2h_meetings", "league_tier",
    "mkt_prob_home", "mkt_prob_draw", "mkt_prob_away", "mkt_has_odds",
    "mkt_prob_over25", "mkt_ou_has",
)

MKT_DEFAULTS = {"home_win": .44, "draw": .26, "away_win": .30}
OVER_25_DEFAULT = .52


@dataclass(frozen=True)
class FeatureVector:
    version: str
    columns: tuple[str, ...]
    values: tuple[float, ...]

    def as_list(self) -> list[float]:
        return list(self.values)


def artifact_compatible(meta: dict | None) -> tuple[bool, str]:
    if not isinstance(meta, dict):
        return False, "MISSING_METADATA"
    if meta.get("feature_schema_version") != FEATURE_SCHEMA_VERSION:
        return False, "FEATURE_SCHEMA_VERSION_MISMATCH"
    if tuple(meta.get("feature_columns") or ()) != FEATURE_COLUMNS:
        return False, "FEATURE_COLUMN_ORDER_MISMATCH"
    return True, "COMPATIBLE"


def build_feature_vector(
    *, home_form: dict, away_form: dict, h2h: dict, league_tier: int,
    odds: dict | None,
) -> FeatureVector:
    """Build normalized values shared by training/replay/live.

    H2H meetings are capped at ten and scaled to [0, 1].  League tier follows
    the historical training representation (tier / 2).  Missing market values
    use the same declared defaults as training and carry explicit presence
    flags.
    """
    odds = odds or {}
    implied = odds.get("implied") if isinstance(odds.get("implied"), dict) else {}
    has_market = bool(implied)
    over25 = exact_total_probability(odds, 2.5, "over")
    values = {
        "home_win_rate_5": home_form["win_rate_5"],
        "home_win_rate_10": home_form["win_rate_10"],
        "home_draw_rate_5": home_form["draw_rate_5"],
        "home_goals_scored_5": home_form["goals_scored_5"],
        "home_goals_conceded_5": home_form["goals_conceded_5"],
        "home_home_win_rate_5": home_form["venue_win_rate_5"],
        "home_home_goals_5": home_form["venue_goals_5"],
        "away_win_rate_5": away_form["win_rate_5"],
        "away_win_rate_10": away_form["win_rate_10"],
        "away_draw_rate_5": away_form["draw_rate_5"],
        "away_goals_scored_5": away_form["goals_scored_5"],
        "away_goals_conceded_5": away_form["goals_conceded_5"],
        "away_away_win_rate_5": away_form["venue_win_rate_5"],
        "away_away_goals_5": away_form["venue_goals_5"],
        "h2h_home_win_rate": h2h["home_win_rate"],
        "h2h_avg_goals": h2h["avg_goals"],
        "h2h_btts_rate": h2h["btts_rate"],
        "h2h_meetings": min(max(float(h2h.get("meetings") or 0), 0), 10) / 10,
        "league_tier": min(max(float(league_tier), 1), 3) / 2,
        "mkt_prob_home": implied.get("home_win", MKT_DEFAULTS["home_win"]),
        "mkt_prob_draw": implied.get("draw", MKT_DEFAULTS["draw"]),
        "mkt_prob_away": implied.get("away_win", MKT_DEFAULTS["away_win"]),
        "mkt_has_odds": 1.0 if has_market else 0.0,
        "mkt_prob_over25": over25 if over25 is not None else OVER_25_DEFAULT,
        "mkt_ou_has": 1.0 if over25 is not None else 0.0,
    }
    return FeatureVector(
        version=FEATURE_SCHEMA_VERSION,
        columns=FEATURE_COLUMNS,
        values=tuple(float(values[column]) for column in FEATURE_COLUMNS),
    )
