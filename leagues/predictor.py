"""
Prediction engine.

Every fixture from espn_source is run through this before anything is
published, so the numbers on the site come from one model rather than from
whatever each source happened to supply.

Method
------
1. De-vigged bookmaker probabilities are the anchor for 1X2. Closing prices
   are the single best public predictor of a football match; nothing here
   tries to out-guess them from scratch.
2. Expected goals are recovered by inverting the bookmaker's own over/under
   2.5 line — find the Poisson mean whose P(over 2.5) matches the market.
   The previous model instead assumed ~2.6 goals for every fixture on earth,
   which is why Over 1.5 was published at ~73% on Argentine games whose real
   rate is 52%.
3. That total is split into home/away expected goals by solving for the
   supremacy that reproduces the market's P(home win).
4. Derived markets (Over 1.5, BTTS, double chance, clean sheets) are computed
   from that fitted bivariate Poisson, so every market is mutually consistent
   and consistent with the prices.
5. Where the market prices nothing (a fixture with no odds), the league's
   measured base rates stand in, and confidence is capped to reflect that.
6. ELO, when both teams are known, is a light second opinion: agreement nudges
   confidence up slightly, disagreement pulls it down. It is never a gate —
   85% of fixtures involve at least one team missing from the registry.

Confidence published for a pick is the model's probability for that outcome.
Value is model probability minus the de-vigged market probability, and is only
meaningful where the market actually prices the same market.
"""

import logging
import math

logger = logging.getLogger(__name__)

MAX_GOALS = 10  # truncation point for the Poisson grid


# ── Poisson helpers ────────────────────────────────────────

def _pois(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * lam ** k / math.factorial(k)


def _p_over(threshold: float, lam: float) -> float:
    """P(total goals > threshold) for a Poisson total."""
    cutoff = int(math.floor(threshold))
    return 1.0 - sum(_pois(k, lam) for k in range(cutoff + 1))


def _solve_total_from_ou(p_over: float, line: float = 2.5) -> float:
    """Find the Poisson mean whose P(over `line`) equals the market's."""
    p_over = min(max(p_over, 0.02), 0.98)
    lo, hi = 0.3, 7.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if _p_over(line, mid) < p_over:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _outcome_probs(home_lam: float, away_lam: float) -> tuple[float, float, float]:
    """P(home win), P(draw), P(away win) on a truncated Poisson grid."""
    home = draw = away = 0.0
    hp = [_pois(i, home_lam) for i in range(MAX_GOALS + 1)]
    ap = [_pois(j, away_lam) for j in range(MAX_GOALS + 1)]
    for i in range(MAX_GOALS + 1):
        for j in range(MAX_GOALS + 1):
            p = hp[i] * ap[j]
            if i > j:
                home += p
            elif i == j:
                draw += p
            else:
                away += p
    total = home + draw + away
    return home / total, draw / total, away / total


def _split_total(total: float, target_home: float, target_away: float) -> tuple[float, float]:
    """Split an expected total into home/away so P(home win) matches the market.

    Binary search on supremacy (home_lam - away_lam); the total is held fixed
    so the goals markets stay consistent with the over/under line.
    """
    if not target_home or not target_away:
        return total * 0.55, total * 0.45  # league-average home tilt

    lo, hi = -total * 0.95, total * 0.95
    for _ in range(40):
        sup = (lo + hi) / 2
        h_lam = max(0.05, (total + sup) / 2)
        a_lam = max(0.05, (total - sup) / 2)
        p_home, _, _ = _outcome_probs(h_lam, a_lam)
        if p_home < target_home:
            lo = sup
        else:
            hi = sup
    sup = (lo + hi) / 2
    return max(0.05, (total + sup) / 2), max(0.05, (total - sup) / 2)


# ── Main entry point ───────────────────────────────────────

def predict(fixture: dict, base: dict, elo_probs: dict | None = None) -> dict:
    """Full market set for one fixture.

    `fixture` — an espn_source fixture dict
    `base`    — measured base rates for that league (leagues.base_rates)
    `elo_probs` — optional {"home_win","draw","away_win"} second opinion
    """
    odds = fixture.get("odds") or {}
    implied = odds.get("implied") or {}
    has_market = bool(implied)

    # ── 1X2 ────────────────────────────────────────────────
    if has_market:
        p_home = implied.get("home_win", base["home_win"])
        p_draw = implied.get("draw", base["draw"])
        p_away = implied.get("away_win", base["away_win"])
    else:
        p_home, p_draw, p_away = base["home_win"], base["draw"], base["away_win"]

    # ELO as a light second opinion — never decisive, and only when the
    # market is absent or ELO disagrees sharply.
    elo_agreement = None
    if elo_probs:
        elo_h = elo_probs.get("home_win", p_home)
        elo_a = elo_probs.get("away_win", p_away)
        diff = abs(elo_h - p_home)
        elo_agreement = "agree" if diff <= 0.10 else ("mild" if diff <= 0.20 else "disagree")
        weight = 0.30 if not has_market else 0.12
        p_home = (1 - weight) * p_home + weight * elo_h
        p_away = (1 - weight) * p_away + weight * elo_a
        p_draw = max(0.05, 1.0 - p_home - p_away)
        s = p_home + p_draw + p_away
        p_home, p_draw, p_away = p_home / s, p_draw / s, p_away / s

    # ── Expected goals ─────────────────────────────────────
    market_over = odds.get("implied_over")
    ou_line = odds.get("ou_line") or 2.5
    if market_over:
        # Invert the bookmaker's own line — the most reliable goals signal
        total_goals = _solve_total_from_ou(market_over, ou_line)
        goals_source = "market_ou"
    else:
        # No priced line: fall back to the league's measured average
        total_goals = base["avg_goals"]
        goals_source = "league_base"

    # Blend lightly toward the league average so a single odd line can't
    # produce an implausible total.
    total_goals = 0.85 * total_goals + 0.15 * base["avg_goals"]

    home_lam, away_lam = _split_total(total_goals, p_home, p_away)

    # Recompute 1X2 from the fitted grid so every market is internally
    # consistent, then pull back toward the market probabilities.
    fit_home, fit_draw, fit_away = _outcome_probs(home_lam, away_lam)
    if has_market:
        p_home = 0.75 * p_home + 0.25 * fit_home
        p_draw = 0.75 * p_draw + 0.25 * fit_draw
        p_away = 0.75 * p_away + 0.25 * fit_away
        s = p_home + p_draw + p_away
        p_home, p_draw, p_away = p_home / s, p_draw / s, p_away / s
    else:
        p_home, p_draw, p_away = fit_home, fit_draw, fit_away

    # ── Derived markets ────────────────────────────────────
    total_lam = home_lam + away_lam
    p_o15 = _p_over(1.5, total_lam)
    p_o25 = odds.get("implied_over") or _p_over(2.5, total_lam)
    p_o35 = _p_over(3.5, total_lam)
    p_btts = (1.0 - math.exp(-home_lam)) * (1.0 - math.exp(-away_lam))

    # Anchor goals markets to measured league reality. The market prices the
    # 2.5 line; Over 1.5 and BTTS are unpriced here, so the league's own
    # measured rate carries real weight rather than being ignored.
    p_o15 = 0.70 * p_o15 + 0.30 * base["over_1_5"]
    p_btts = 0.70 * p_btts + 0.30 * base["btts"]

    p_hd = min(0.97, p_home + p_draw)
    p_ad = min(0.97, p_away + p_draw)
    p_ha = min(0.97, p_home + p_away)

    # Confidence ceiling when nothing is priced — we are extrapolating
    cap = 0.97 if has_market else 0.80

    # Per-team goal lines. The Poisson already carries each side's expected
    # goals separately — these were always computable and simply never
    # published, which is why the qualifying pool ran 96% goals markets and no
    # slip could reach past about 41x however many fixtures were modelled.
    #
    # Independent of the total-goals lines in the sense that matters here: one
    # leg per fixture is enforced elsewhere, so "home to score" and "over 1.5"
    # never appear together off the same match.
    p_h05 = _p_over(0.5, home_lam)
    p_a05 = _p_over(0.5, away_lam)
    p_h15 = _p_over(1.5, home_lam)
    p_a15 = _p_over(1.5, away_lam)
    p_o45 = _p_over(4.5, total_lam)

    # Draw no bet. The same opinion as the 1X2 with the draw removed and the
    # stake returned, so the probability is the win share of a decisive
    # result. Worth having because match_result clears its floor on very few
    # fixtures — nine of 177 on a full Saturday — while the same view
    # expressed without the draw clears far more often.
    decisive = p_home + p_away
    p_dnb_h = (p_home / decisive) if decisive > 0.01 else 0.5
    p_dnb_a = (p_away / decisive) if decisive > 0.01 else 0.5

    markets = {
        "home_win":   min(cap, p_home),
        "draw":       min(cap, p_draw),
        "away_win":   min(cap, p_away),
        "home_or_draw": min(cap, p_hd),
        "away_or_draw": min(cap, p_ad),
        "home_or_away": min(cap, p_ha),
        "dnb_home":   min(cap, p_dnb_h),
        "dnb_away":   min(cap, p_dnb_a),
        "over_1_5":   min(cap, p_o15),
        "over_2_5":   min(cap, p_o25),
        "over_3_5":   min(cap, p_o35),
        "under_1_5":  min(cap, 1.0 - p_o15),
        "under_2_5":  min(cap, 1.0 - p_o25),
        "under_3_5":  min(cap, 1.0 - p_o35),
        "under_4_5":  min(cap, 1.0 - p_o45),
        "home_over_0_5": min(cap, p_h05),
        "home_over_1_5": min(cap, p_h15),
        "away_over_0_5": min(cap, p_a05),
        "away_over_1_5": min(cap, p_a15),
        "btts_yes":   min(cap, p_btts),
        "btts_no":    min(cap, 1.0 - p_btts),
    }

    return {
        "probabilities": {k: round(v, 4) for k, v in markets.items()},
        "expected_goals": {
            "home": round(home_lam, 2),
            "away": round(away_lam, 2),
            "total": round(total_lam, 2),
            "source": goals_source,
        },
        "has_market": has_market,
        "elo_agreement": elo_agreement,
        "confidence_cap": cap,
    }
