"""
Turn model output into publishable picks.

One pick = one market on one fixture, carrying the model's probability, the
real bookmaker price where one exists, and the value edge between them.

Odds policy
-----------
Where DraftKings prices the market (1X2, Over/Under 2.5) the real decimal
price is published, so what the site shows matches what a user sees at a
sportsbook. Where it does not (Over 1.5, BTTS, double chance) the price is
marked `estimated` and derived as a fair price plus a typical margin — it is
labelled as an estimate rather than passed off as a quote.

Why estimated prices are not 1/probability: pricing a 75% shot at exactly
1.33 implies zero margin and zero edge by construction, which is what the
previous version did. Real books charge roughly 5-7% on these markets, so the
estimate reflects what is actually obtainable.
"""

import logging

logger = logging.getLogger(__name__)

# Typical bookmaker margin on markets DraftKings does not price for us
ESTIMATE_MARGIN = 1.06

MARKET_LABELS = {
    "home_win": "{home} Win",
    "away_win": "{away} Win",
    "draw": "Draw",
    "home_or_draw": "{home} or Draw",
    "away_or_draw": "{away} or Draw",
    "home_or_away": "{home} or {away}",
    "over_1_5": "Over 1.5 Goals",
    "over_2_5": "Over 2.5 Goals",
    "over_3_5": "Over 3.5 Goals",
    "under_2_5": "Under 2.5 Goals",
    "under_3_5": "Under 3.5 Goals",
    "btts_yes": "Both Teams to Score",
    "btts_no": "Both Teams to Score - No",
}

MARKET_GROUP = {
    "home_win": "match_result", "away_win": "match_result", "draw": "match_result",
    "home_or_draw": "double_chance", "away_or_draw": "double_chance",
    "home_or_away": "double_chance",
    "over_1_5": "goals", "over_2_5": "goals", "over_3_5": "goals",
    "under_2_5": "goals", "under_3_5": "goals",
    "btts_yes": "btts", "btts_no": "btts",
}

# Markets DraftKings gives us a real price for, mapped to the odds key
REAL_ODDS_KEY = {
    "home_win": "home_win", "away_win": "away_win", "draw": "draw",
    "over_2_5": "over_2_5", "under_2_5": "under_2_5",
}


def _estimated_price(prob: float) -> float:
    """Fair price plus a typical book margin, floored at a sane minimum."""
    if prob <= 0:
        return 1.01
    fair = 1.0 / prob
    return max(1.01, round(fair / ESTIMATE_MARGIN, 2))


def build_picks(fixture: dict, model: dict, min_confidence: float = 0.55,
                fit: dict | None = None) -> list[dict]:
    """All viable picks for one fixture, best first.

    A pick must clear `min_confidence` and carry odds of at least 1.05.
    Double chance is additionally required to be genuinely strong, since it is
    a low-price market that otherwise crowds out everything else.

    The model probability is passed through the empirical calibrator before
    anything else looks at it, so the confidence threshold, the estimated
    price, the value edge and the accumulator search all see the corrected
    number. Calibrating only at display time would have left selection
    choosing between the same over-stated candidates and merely relabelled
    them on the way out.
    """
    from leagues.calibrator import calibrate

    if fit is None:
        from leagues.calibrator import fit_calibration
        fit = fit_calibration()

    raw_probs = model["probabilities"]
    odds = fixture.get("odds") or {}
    home = fixture["home"]["name"]
    away = fixture["away"]["name"]

    picks = []
    for market, raw_prob in raw_probs.items():
        prob = calibrate(raw_prob, MARKET_GROUP[market], fit)
        if prob < min_confidence:
            continue
        # Double chance only when it is genuinely safe — otherwise it wins
        # every selection on price alone and adds no information.
        if MARKET_GROUP[market] == "double_chance" and prob < 0.78:
            continue
        # Rarely useful and usually mispriced against us
        if market in ("home_or_away", "over_3_5", "under_3_5"):
            continue

        real_key = REAL_ODDS_KEY.get(market)
        real_price = odds.get(real_key) if real_key else None

        if real_price and real_price >= 1.05:
            price = float(real_price)
            is_real = True
        else:
            price = _estimated_price(prob)
            is_real = False

        if price < 1.05:
            continue

        # Value only means something against a real, de-vigged market price
        edge = None
        if is_real:
            if market in ("home_win", "away_win", "draw"):
                mkt_prob = (odds.get("implied") or {}).get(market)
            elif market == "over_2_5":
                mkt_prob = odds.get("implied_over")
            elif market == "under_2_5":
                mkt_prob = odds.get("implied_under")
            else:
                mkt_prob = None
            if mkt_prob:
                edge = round(prob - mkt_prob, 4)

        picks.append({
            "match_id": fixture["match_id"],
            "market": market,
            "market_group": MARKET_GROUP[market],
            "prediction": MARKET_LABELS[market].format(home=home, away=away),
            "confidence": round(prob, 4),
            # Kept so the calibration's effect stays auditable after the fact
            "raw_confidence": round(raw_prob, 4),
            "odds": round(price, 2),
            "odds_are_real": is_real,
            "odds_provider": odds.get("provider") if is_real else None,
            "edge": edge,
            "expected_value": round(prob * price - 1.0, 4),
            "_fixture": fixture,
            "_model": model,
        })

    picks.sort(key=lambda p: p["confidence"], reverse=True)
    return picks


def to_game(pick: dict) -> dict:
    """Frontend game object for one pick."""
    f = pick["_fixture"]
    m = pick["_model"]
    eg = m["expected_goals"]
    conf = pick["confidence"]

    return {
        "fixture_id": abs(hash(pick["match_id"])) % 1_000_000,
        "match_id": pick["match_id"],
        "home_team": f["home"]["name"],
        "away_team": f["away"]["name"],
        "home_team_logo": f["home"].get("logo"),
        "away_team_logo": f["away"].get("logo"),
        "league": f["league"],
        "league_slug": f["league_slug"],
        "date": f["commence_time"],
        "kickoff": f["commence_time"],
        "venue": f.get("venue", {}).get("name"),
        "venue_city": f.get("venue", {}).get("city"),
        "broadcast": f.get("broadcast") or [],
        "home_form": f["home"].get("form"),
        "away_form": f["away"].get("form"),
        "home_record": f["home"].get("record"),
        "away_record": f["away"].get("record"),
        # Same detail nested under the shape the prediction card already reads
        "match_info": {
            "kickoff_utc": f["commence_time"],
            "venue": f.get("venue", {}).get("name"),
            "city": f.get("venue", {}).get("city"),
            "country": f.get("venue", {}).get("country"),
            "broadcast": ", ".join(f.get("broadcast") or []) or None,
            "home_form": f["home"].get("form"),
            "away_form": f["away"].get("form"),
            "home_record": f["home"].get("record"),
            "away_record": f["away"].get("record"),
        },
        "prediction": pick["prediction"],
        "prediction_type": pick["market_group"],
        "market": pick["market"],
        "prediction_value": pick["prediction"],
        "readable_prediction": pick["prediction"],
        "confidence": conf,
        "raw_confidence": pick.get("raw_confidence"),
        "odds": pick["odds"],
        "estimated_odds": pick["odds"],
        "real_odds": pick["odds"] if pick["odds_are_real"] else None,
        "odds_are_real": pick["odds_are_real"],
        "odds_provider": pick["odds_provider"],
        "edge": pick["edge"],
        "expected_value": pick["expected_value"],
        "expected_goals": eg["total"],
        "expected_home_goals": eg["home"],
        "expected_away_goals": eg["away"],
        "risk_score": round(1.0 - conf, 3),
        "risk_level": "low" if conf >= 0.75 else ("medium" if conf >= 0.62 else "high"),
        "model_type": "market_poisson" if m["has_market"] else "league_base",
        "elo_agreement": m.get("elo_agreement"),
        "models_agreed": 3 if m.get("elo_agreement") == "agree" else 2,
    }
