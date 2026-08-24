"""
Pipeline orchestrator.

Answers the question "does everything go through our own model?" with a
single path:

    ESPN fixtures + real odds
        -> per-league measured base rates
        -> ELO lookup (optional, never a gate)
        -> predictor.predict()      <- one model, every fixture
        -> picks.build_picks()      <- markets, prices, value
        -> category / rollover selection

Nothing reaches the site without passing through predictor.predict(). The
result is cached for an hour; a full refresh takes a few seconds because every
league is fetched in one ranged request.
"""

import logging
import time

logger = logging.getLogger(__name__)

_CACHE: dict = {"picks": None, "fixtures": None, "ts": 0.0}
_TTL = 3600


def _elo_for(home: str, away: str):
    """ELO second opinion, or None when either team is unrated."""
    try:
        from leagues.ml_overlay import elo_probabilities
        return elo_probabilities(home, away)
    except Exception:
        return None


def run_pipeline(days_ahead: int = 3, force: bool = False) -> tuple[list[dict], list[dict]]:
    """Return (all_picks, fixtures). Every fixture passes through the model."""
    now = time.time()
    if not force and _CACHE["picks"] is not None and (now - _CACHE["ts"]) < _TTL:
        return _CACHE["picks"], _CACHE["fixtures"]

    from leagues.espn_source import get_fixtures, ESPN_CLUB_LEAGUES
    from leagues.base_rates import get_base_rates, rates_for
    from leagues.predictor import predict
    from leagues.picks import MIN_CANDIDATE_CONFIDENCE, build_picks
    from leagues.calibrator import fit_calibration
    from leagues import ml_models
    from leagues.team_history import HistoryIndex

    fixtures = get_fixtures(days_ahead=days_ahead, force=force)

    # Real, bookable prices and the margin behind each one. Never fatal: a
    # book that is unreachable leaves the fixtures exactly as ESPN supplied
    # them, and the card falls back to estimated prices as it always has.
    sb_matched = 0
    try:
        from leagues import sportybet
        sb_matched = sportybet.apply_to_fixtures(fixtures)
    except Exception as e:
        logger.warning(f"SportyBet pricing unavailable: {e}")

    cached_rates = get_base_rates(ESPN_CLUB_LEAGUES)
    # Fitted once per pipeline run; every pick is corrected against the same
    # snapshot so a mid-run refit cannot make two picks incomparable.
    fit = fit_calibration()

    # Second opinion from the trained ensemble, in shadow only: it is recorded
    # on each pick and evaluated against results, and does not move a published
    # number. Built once per run because the history index is a 15s fetch.
    try:
        history = HistoryIndex()
    except Exception as e:
        logger.warning(f"team history unavailable, ML second opinion off: {e}")
        history = None

    all_picks: list[dict] = []
    priced = unpriced = with_elo = 0

    for fx in fixtures:
        base = rates_for(fx["league_slug"], cached_rates)
        elo = _elo_for(fx["home"]["name"], fx["away"]["name"])
        if elo:
            with_elo += 1
        model = predict(fx, base, elo)
        if history is not None:
            try:
                model["ml"] = ml_models.predict_fixture(fx, history)
            except Exception:
                model["ml"] = None
        if model["has_market"]:
            priced += 1
        else:
            unpriced += 1
        fx["_model"] = model
        all_picks.extend(build_picks(
            fx, model, min_confidence=MIN_CANDIDATE_CONFIDENCE, fit=fit))

    logger.info(
        f"Pipeline: {len(fixtures)} fixtures ({priced} priced, {unpriced} base-rate only, "
        f"{sb_matched} with SportyBet prices, {with_elo} with ELO, "
        f"{sum(1 for f in fixtures if (f.get('_model') or {}).get('ml'))} with ML) "
        f"-> {len(all_picks)} candidate picks "
        f"(calibrated on {fit.get('n', 0)} settled legs)"
    )

    _CACHE.update({"picks": all_picks, "fixtures": fixtures, "ts": now})
    return all_picks, fixtures


def picks_for_date(date_str: str, all_picks: list[dict] | None = None) -> list[dict]:
    """Picks whose fixture kicks off on `date_str` (UTC, YYYY-MM-DD)."""
    if all_picks is None:
        all_picks, _ = run_pipeline()
    return [p for p in all_picks if p["_fixture"]["commence_time"][:10] == date_str]
