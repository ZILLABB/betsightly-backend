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
import threading
import time
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_CACHE: dict = {"entries": {}, "healthy_entries": {}}
_TTL = 3600
_PREPARED_STALE_TTL = 6 * 3600
_PIPELINE_LOCK = threading.Lock()
_PREWARM_LOCK = threading.Lock()
_PREWARMING = False


def _parse_kickoff(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def kickoff_wat_date(value: str | None) -> str | None:
    """Audience-facing fixture day in Nigeria (UTC+1, no DST)."""
    parsed = _parse_kickoff(str(value or ""))
    if parsed is None:
        return None
    return (parsed + timedelta(hours=1)).date().isoformat()


def _filter_cached(entry: dict, days_ahead: int,
                   now: datetime) -> tuple[list[dict], list[dict]]:
    end = now + timedelta(days=days_ahead)
    fixtures = [fixture for fixture in entry["fixtures"]
                if (kickoff := _parse_kickoff(fixture.get("commence_time")))
                and now <= kickoff <= end]
    fixture_ids = {str(fixture.get("match_id")) for fixture in fixtures}
    picks = [pick for pick in entry["picks"]
             if str(pick.get("match_id")) in fixture_ids]
    return picks, fixtures


def _covering_entry(days_ahead: int, now_ts: float,
                    require_complete: bool = False,
                    allow_stale: bool = False) -> dict | None:
    now_dt = datetime.fromtimestamp(now_ts, timezone.utc)
    requested_end = now_dt + timedelta(days=days_ahead)

    def has_actionable_fixture(entry: dict) -> bool:
        return any(
            (kickoff := _parse_kickoff(fixture.get("commence_time")))
            and now_dt <= kickoff <= requested_end
            for fixture in entry.get("fixtures") or []
        )

    entries = list(_CACHE.get("entries", {}).values())
    entries.extend(_CACHE.get("healthy_entries", {}).values())
    # A complete entry may be present in both collections. Identity-based
    # de-duplication keeps selection deterministic without copying large
    # evaluated boards.
    unique = {id(entry): entry for entry in entries}.values()
    valid = [entry for entry in unique
             if (now_ts - entry["ts"] < (
                 _PREPARED_STALE_TTL if allow_stale else _TTL
             ))
             and entry["metadata"]["requested_days"] >= days_ahead
             and has_actionable_fixture(entry)
             and (not require_complete
                  or (entry["metadata"].get("provider") or {}).get(
                      "complete", True))]
    if not valid:
        return None
    # Prefer a healthy board while it remains within the explicit stale-safe
    # window. Within the same health class, newest wins; requested horizon is
    # only the final tie-breaker. This prevents a smaller, older degraded board
    # from masking a newer complete covering board.
    return max(
        valid,
        key=lambda item: (
            bool((item["metadata"].get("provider") or {}).get(
                "complete", True
            )),
            float(item["ts"]),
            -int(item["metadata"]["requested_days"]),
        ),
    )


def _store_cache_entry(days_ahead: int, picks: list[dict],
                       fixtures: list[dict], now: float,
                       now_dt: datetime, provider: dict,
                       decision_snapshot_id: str | None = None) -> None:
    """Store one evaluated horizon; kept small so coverage rules are testable."""
    entry = {
        "picks": picks,
        "fixtures": fixtures,
        "ts": now,
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "requested_days": days_ahead,
            "coverage_start": now_dt.isoformat(),
            "coverage_end": (now_dt + timedelta(days=days_ahead)).isoformat(),
            "fixture_count": len(fixtures),
            "provider": provider,
            "decision_snapshot_id": decision_snapshot_id,
        },
    }
    _CACHE.setdefault("entries", {})[days_ahead] = entry
    if provider.get("complete", True):
        _CACHE.setdefault("healthy_entries", {})[days_ahead] = entry


def prepared_board_status(days_ahead: int = 7) -> dict:
    """Describe whether an evaluated board is ready for interaction.

    Provider completeness is reported separately. A board with useful fixtures
    from 99/116 leagues is degraded, not absent; treating it as perpetually
    cold made every public Builder request return ``board_refreshing`` while
    repeatedly refetching the same failing competitions.
    """
    now = time.time()
    entry = _covering_entry(days_ahead, now, allow_stale=True)
    if not entry:
        return {"ready": False, "requested_days": days_ahead}
    provider = entry["metadata"].get("provider") or {}
    age_seconds = round(now - entry["ts"], 1)
    return {
        **entry["metadata"],
        "ready": bool(entry.get("fixtures")),
        "complete": bool(provider.get("complete", True)),
        "degraded": not bool(provider.get("complete", True)),
        "successful_league_count": int(
            provider.get("successful_league_count")
            or len(provider.get("successful_leagues") or [])
        ),
        "requested_league_count": int(
            provider.get("requested_league_count")
            or len(provider.get("leagues_requested") or [])
        ),
        "failed_league_count": int(
            provider.get("failed_league_count")
            or len(provider.get("failed_leagues") or [])
        ),
        "age_seconds": age_seconds,
        "stale": bool(age_seconds >= _TTL),
        "board_source": (
            "stale_fallback" if age_seconds >= _TTL else "cache"
        ),
        "board_snapshot_id": entry["metadata"].get(
            "decision_snapshot_id"
        ),
        "raw_fixture_count": int(provider.get("fixture_count") or 0),
        "evaluated_fixture_count": len(entry.get("fixtures") or []),
        "refreshing": bool(_PREWARMING),
    }


def prepared_pipeline(days_ahead: int = 7) -> tuple[list[dict], list[dict]]:
    """Read the most recent evaluated board without provider fan-out.

    Only the interactive Builder uses this path after ``prepared_board_status``
    says it is ready. Normal pipeline calls still require complete provider
    coverage and therefore retry partial ESPN caches on scheduled refreshes.
    """
    now = time.time()
    now_dt = datetime.now(timezone.utc)
    # Interactive requests may safely keep using the last evaluated board
    # while its replacement is prepared. Kickoff filtering below removes games
    # that have since started; selection policy and bookability are re-applied.
    entry = _covering_entry(
        days_ahead, now, require_complete=False, allow_stale=True,
    )
    if not entry:
        return [], []
    return _filter_cached(entry, days_ahead, now_dt)


def start_prepared_board_refresh(days_ahead: int = 7,
                                 force: bool = True) -> bool:
    """Singleflight background preparation for an interactive Builder board."""
    global _PREWARMING
    with _PREWARM_LOCK:
        if _PREWARMING:
            return False
        _PREWARMING = True

    def _work():
        global _PREWARMING
        try:
            run_pipeline(days_ahead=days_ahead, force=force)
        except Exception as exc:
            logger.error("prepared board refresh failed: %s", exc, exc_info=True)
        finally:
            with _PREWARM_LOCK:
                _PREWARMING = False

    threading.Thread(
        target=_work, daemon=True, name="weekly-board-prewarm"
    ).start()
    return True


_HISTORY_PREWARM_LOCK = threading.Lock()
_HISTORY_PREWARMING = False


def start_history_prewarm() -> bool:
    """Refresh historical inputs off the publication and request paths.

    Each artifact has a filesystem process claim. This is not a distributed
    lease across separate Render instances; staging must verify topology.
    """
    global _HISTORY_PREWARMING
    with _HISTORY_PREWARM_LOCK:
        if _HISTORY_PREWARMING:
            return False
        _HISTORY_PREWARMING = True

    def _work():
        global _HISTORY_PREWARMING
        try:
            from leagues.base_rates import get_base_rates
            from leagues.team_history import load
            get_base_rates()
            load()
        except Exception as exc:
            logger.warning("history prewarm failed: %s", exc, exc_info=True)
        finally:
            with _HISTORY_PREWARM_LOCK:
                _HISTORY_PREWARMING = False

    threading.Thread(target=_work, daemon=True,
                     name="history-prewarm").start()
    return True


def _elo_for(fixture: dict, ratings: dict | None = None):
    """Competition-aware ELO opinion, isolated by club/national team type."""
    try:
        from leagues.elo_engine import probabilities_for_fixture
        return probabilities_for_fixture(fixture, ratings or {})
    except Exception:
        return None


def run_pipeline(days_ahead: int = 3, force: bool = False) -> tuple[list[dict], list[dict]]:
    """Return (all_picks, fixtures). Every fixture passes through the model."""
    days_ahead = max(1, min(14, int(days_ahead)))
    now = time.time()
    now_dt = datetime.now(timezone.utc)
    if not force and (cached := _covering_entry(
            days_ahead, now, require_complete=True)):
        return _filter_cached(cached, days_ahead, now_dt)

    with _PIPELINE_LOCK:
        now = time.time()
        now_dt = datetime.now(timezone.utc)
        if not force and (cached := _covering_entry(
                days_ahead, now, require_complete=True)):
            return _filter_cached(cached, days_ahead, now_dt)

        return _build_pipeline(days_ahead, force, now, now_dt)


def _build_pipeline(days_ahead: int, force: bool, now: float,
                    now_dt: datetime) -> tuple[list[dict], list[dict]]:
    from leagues.espn_source import (
        ESPN_CLUB_LEAGUES, cache_metadata as espn_cache_metadata,
        get_fixtures,
    )
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

    # Requests and the 08:00 publication path only consume completed history.
    # Cold ESPN refresh runs independently in start_history_prewarm().
    cached_rates = get_base_rates(ESPN_CLUB_LEAGUES, allow_refresh=False)
    try:
        from leagues.elo_engine import get_ratings
        ratings = get_ratings(ESPN_CLUB_LEAGUES)
    except Exception as e:
        logger.warning(f"competition-aware ELO unavailable: {e}")
        ratings = {}
    # Fitted once per pipeline run; every pick is corrected against the same
    # snapshot so a mid-run refit cannot make two picks incomparable.
    fit = fit_calibration()

    # Second opinion from the trained ensemble, in shadow only: it is recorded
    # on each pick and evaluated against results, and does not move a published
    # number. Built once per run because the history index is a 15s fetch.
    try:
        from leagues.team_history import load as load_team_history
        history = HistoryIndex(load_team_history(allow_refresh=False))
    except Exception as e:
        logger.warning(f"team history unavailable, ML second opinion off: {e}")
        history = None

    all_picks: list[dict] = []
    priced = unpriced = with_elo = 0

    for fx in fixtures:
        base = rates_for(fx["league_slug"], cached_rates)
        fx["competition_historical_sample"] = int(base.get("matches") or 0)
        fx["base_rate_source"] = base.get("base_rate_source", "competition")
        elo = _elo_for(fx, ratings)
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

    provider = espn_cache_metadata()
    # Preserve the evaluated environment before any product optimizer narrows
    # it. Archiving is observability: failure is logged and never blocks picks.
    decision_snapshot_id = None
    try:
        from leagues.decision_archive import archive_board
        decision_snapshot_id = archive_board(
            all_picks, fixtures, horizon=days_ahead, provider=provider,
            calibration=fit, generated_at=now_dt,
        )
    except Exception as exc:
        logger.error("decision board archive unavailable: %s", exc,
                     exc_info=True)
    _store_cache_entry(
        days_ahead, all_picks, fixtures, now, now_dt, provider,
        decision_snapshot_id=decision_snapshot_id,
    )
    return all_picks, fixtures


def picks_for_date(date_str: str, all_picks: list[dict] | None = None) -> list[dict]:
    """Picks whose fixture kicks off on the WAT calendar `date_str`."""
    if all_picks is None:
        all_picks, _ = run_pipeline()
    return [p for p in all_picks
            if kickoff_wat_date(p["_fixture"].get("commence_time")) == date_str]
