"""
Auto-refresh World Cup fixtures from ESPN (free, no API key).

The Odds API key is exhausted, so new fixtures (knockout rounds) can't come
from there. ESPN's scoreboard lists upcoming WC matches; we generate odds
from national ELO ratings (worldcup/data/national_elo.json) using the same
Poisson math the model uses.

Called from build_daily_accumulators: if any of the next few days have no
fixtures on file, we pull them from ESPN and regenerate predictions. Runs at
most once per REFRESH_INTERVAL to avoid hammering ESPN on every cache miss.
"""

import json
import hashlib
import logging
import math
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

logger = logging.getLogger(__name__)
DATA_DIR = Path(__file__).parent / "data"

ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard"

# ESPN name -> our canonical name (must match national_elo.json keys)
ESPN_NAME_MAP = {
    "United States": "USA",
    "Congo DR": "DR Congo",
    "Bosnia-Herzegovina": "Bosnia & Herzegovina",
    "Cabo Verde": "Cape Verde",
    "Côte d'Ivoire": "Ivory Coast",
    "Türkiye": "Turkey",
    "Czechia": "Czech Republic",
    "Korea Republic": "South Korea",
    "IR Iran": "Iran",
}

_last_refresh = 0.0
REFRESH_INTERVAL = 6 * 3600  # at most every 6 hours


def _canonical(name: str) -> str:
    return ESPN_NAME_MAP.get(name, name)


def _elo_odds(home: str, away: str, elo_data: dict) -> tuple[dict, dict] | None:
    """Generate implied probabilities + odds from ELO. None if a team is unknown
    (placeholder fixtures like 'Round of 32 3 Winner' get skipped this way)."""
    ratings = elo_data.get("ratings", {})
    if home not in ratings or away not in ratings:
        return None

    h_elo, a_elo = ratings[home], ratings[away]
    home_adv = elo_data.get("home_advantage", 60)
    diff = (h_elo + home_adv) - a_elo

    expected = 1.0 / (1.0 + math.pow(10, -diff / 400.0))
    draw_prob = max(0.08, min(0.28, 0.28 - abs(diff) / 1200.0))
    p_home = max(0.05, expected - 0.5 * draw_prob)
    p_away = max(0.05, 1.0 - p_home - draw_prob)
    total = p_home + draw_prob + p_away
    p_home, draw_prob, p_away = p_home / total, draw_prob / total, p_away / total

    margin = 1.05
    h_odds = round(margin / max(p_home, 0.05), 2)
    d_odds = round(margin / max(draw_prob, 0.05), 2)
    a_odds = round(margin / max(p_away, 0.05), 2)

    attack = elo_data.get("attack_rating", {})
    defense = elo_data.get("defense_rating", {})
    h_atk, a_atk = attack.get(home, 0.6), attack.get(away, 0.6)
    h_def, a_def = defense.get(home, 0.6), defense.get(away, 0.6)

    h_goals = 1.35 * h_atk * (1.0 + (1.0 - a_def))
    a_goals = 1.35 * a_atk * (1.0 + (1.0 - h_def))
    gap = (h_elo - a_elo) / 400.0
    h_goals *= (1.0 + gap * 0.15)
    a_goals *= (1.0 - gap * 0.15)
    exp_total = max(1.5, h_goals + a_goals)

    p_o25 = 1.0 - sum(
        (exp_total ** k) * math.exp(-exp_total) / math.factorial(k) for k in range(3)
    )
    o25_odds = round(margin / max(p_o25, 0.1), 2)
    u25_odds = round(margin / max(1 - p_o25, 0.1), 2)

    implied = {
        "home_win": round(p_home, 4),
        "draw": round(draw_prob, 4),
        "away_win": round(p_away, 4),
        "over_2_5": round(p_o25, 4),
        "under_2_5": round(1 - p_o25, 4),
    }
    best = {
        "home_win": h_odds, "draw": d_odds, "away_win": a_odds,
        "over_2_5": o25_odds, "under_2_5": u25_odds,
    }
    return implied, best


def _fetch_espn_fixtures(days_ahead: int = 7) -> list[dict]:
    """Fetch scheduled WC fixtures from ESPN for the next N days."""
    fixtures = []
    seen = set()
    now = datetime.utcnow()
    for offset in range(days_ahead):
        date_str = (now + timedelta(days=offset)).strftime("%Y%m%d")
        try:
            resp = requests.get(ESPN_SCOREBOARD, params={"dates": date_str}, timeout=20)
            resp.raise_for_status()
            events = resp.json().get("events", [])
        except Exception as e:
            logger.warning(f"ESPN fetch failed for {date_str}: {e}")
            continue

        for ev in events:
            status = ev.get("status", {}).get("type", {}).get("name", "")
            if status != "STATUS_SCHEDULED":
                continue
            comps = ev.get("competitions", [{}])[0]
            teams = comps.get("competitors", [])
            home = next((t for t in teams if t.get("homeAway") == "home"), {})
            away = next((t for t in teams if t.get("homeAway") == "away"), {})
            ht = _canonical(home.get("team", {}).get("displayName", ""))
            at = _canonical(away.get("team", {}).get("displayName", ""))
            date = ev.get("date", "")  # e.g. 2026-06-29T17:00Z
            if not ht or not at or not date:
                continue
            # Normalize to full ISO with seconds
            if date.endswith("Z") and len(date) == 17:
                date = date[:-1] + ":00Z"
            key = f"{ht}|{at}|{date[:10]}"
            if key in seen:
                continue
            seen.add(key)
            fixtures.append({"home_team": ht, "away_team": at, "commence_time": date})
    return fixtures


def ensure_upcoming_fixtures() -> bool:
    """
    Make sure we have fixtures + predictions for upcoming days.
    Returns True if new fixtures were added and predictions regenerated.
    Throttled to once per REFRESH_INTERVAL.
    """
    global _last_refresh
    if time.time() - _last_refresh < REFRESH_INTERVAL:
        return False
    _last_refresh = time.time()

    try:
        fixtures_path = DATA_DIR / "wc_fixtures.json"
        existing = json.loads(fixtures_path.read_text()) if fixtures_path.exists() else []
        existing_keys = {
            f"{f['home_team']}|{f['away_team']}|{f['commence_time'][:10]}" for f in existing
        }

        elo_path = DATA_DIR / "national_elo.json"
        if not elo_path.exists():
            logger.warning("national_elo.json missing — cannot auto-generate fixture odds")
            return False
        elo_data = json.loads(elo_path.read_text())

        espn = _fetch_espn_fixtures()
        added = 0
        for fx in espn:
            key = f"{fx['home_team']}|{fx['away_team']}|{fx['commence_time'][:10]}"
            if key in existing_keys:
                continue
            odds = _elo_odds(fx["home_team"], fx["away_team"], elo_data)
            if odds is None:
                # Unknown team (usually a "Winner of ..." placeholder) — skip until decided
                continue
            fx["id"] = hashlib.md5(
                f"{fx['home_team']}{fx['away_team']}{fx['commence_time']}".encode()
            ).hexdigest()
            fx["implied_prob"], fx["best_odds"] = odds
            existing.append(fx)
            existing_keys.add(key)
            added += 1
            logger.info(f"Auto-added fixture: {fx['home_team']} vs {fx['away_team']} ({fx['commence_time'][:10]})")

        if not added:
            return False

        fixtures_path.write_text(json.dumps(existing, indent=2))

        # Regenerate predictions so the new fixtures flow through the model
        from worldcup.model import generate_all_predictions
        generate_all_predictions()
        logger.info(f"Auto-refresh: {added} new fixtures added, predictions regenerated")
        return True
    except Exception as e:
        logger.error(f"Auto fixture refresh failed: {e}")
        return False
