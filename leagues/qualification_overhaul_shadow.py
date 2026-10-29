"""Read-only four-part qualification audit for BetSightly football.

No database writes, provider requests, price substitution, official settlement,
policy relaxation or publishing. This consumes immutable pregame board exports
and separately verified full-time score exports. The upstream export process
must prove score provenance; a caller-supplied 'verified' flag alone is not
independent verification.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from math import isfinite, log
from typing import Any

PRODUCTS = ("rollover", "banker", "2_odds", "5_odds", "10_odds", "over_1_5")
MIN_MARKET_HOLDOUT = 100
MIN_HOLDOUT_DAYS = 7
MAX_KICKOFF_DRIFT_SECONDS = 1800


def _time(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp without timezone")
    return parsed.astimezone(timezone.utc)


def _probability(value: Any) -> float | None:
    try:
        if isinstance(value, bool):
            return None
        p = float(value)
        return p if isfinite(p) and 0 < p < 1 else None
    except (ValueError, TypeError, OverflowError):
        return None


def _score_market(home: int, away: int, market: str) -> int | None:
    total = home + away
    binary = {
        "home_win": home > away, "draw": home == away,
        "away_win": away > home, "home_or_draw": home >= away,
        "away_or_draw": away >= home, "home_or_away": home != away,
        "btts_yes": home > 0 and away > 0,
        "btts_no": home == 0 or away == 0,
        "dnb_home": None if home == away else home > away,
        "dnb_away": None if home == away else away > home,
    }
    if market in binary:
        return None if binary[market] is None else int(binary[market])
    for prefix, goals in (("over_", total), ("under_", total),
                          ("home_over_", home), ("home_under_", home),
                          ("away_over_", away), ("away_under_", away)):
        if market.startswith(prefix):
            try:
                threshold = float(market[len(prefix):].replace("_", "."))
            except ValueError:
                return None
            if threshold % 1 != .5:
                return None
            return int(goals > threshold) if "over" in prefix else int(goals < threshold)
    return None


def _fixture_key(row: dict) -> tuple[str, str]:
    return (str(row.get("fixture_id") or "").strip(),
            str(row.get("league_slug") or "").strip().casefold())


def _score_provenance(final: dict) -> bool:
    try:
        return (
            final.get("verified") is True
            and str(final.get("status") or "").upper() == "FINAL"
            and str(final.get("period") or "").upper() == "REGULATION"
            and bool(str(final.get("source") or "").strip())
            and bool(str(final.get("source_event_id") or "").strip())
            and all(type(final.get(k)) is int and final[k] >= 0
                    for k in ("home_score", "away_score"))
            and _time(final["verified_at"]) > _time(final["kickoff"])
        )
    except (ValueError, TypeError, KeyError, OverflowError):
        return False


def score_complete_forecast_pool(snapshots: list[dict],
                                 verified_finals: list[dict]) -> dict:
    """Score every captured market, including officially rejected ones.

    Exact fixture ID + league + scheduled kickoff protects cross-competition
    identity. Only the earliest valid before-kickoff forecast is scored.
    Contradictory/duplicate final rows are quarantined, never arbitrated.
    Draw-no-bet pushes and unrecognised markets remain unscored.
    """
    final_index: dict[tuple[str, str], list[dict]] = defaultdict(list)
    reasons: Counter[str] = Counter()
    for final in verified_finals:
        if not isinstance(final, dict) or not all(_fixture_key(final)):
            reasons["invalid_final_identity"] += 1
        elif not _score_provenance(final):
            reasons["unverified_or_nonregulation_final"] += 1
        else:
            final_index[_fixture_key(final)].append(final)

    first: dict[tuple[str, str, str], dict] = {}
    for snapshot in snapshots:
        if not isinstance(snapshot, dict) or not snapshot.get("snapshot_id"):
            reasons["missing_immutable_snapshot_identity"] += 1
            continue
        try:
            captured = _time(snapshot["generated_at"])
        except (ValueError, TypeError, KeyError, OverflowError):
            reasons["missing_snapshot_capture_time"] += 1
            continue
        for candidate in snapshot.get("candidates") or []:
            if not isinstance(candidate, dict):
                reasons["invalid_candidate"] += 1
                continue
            fid, league = _fixture_key(candidate)
            market = str(candidate.get("market") or "").strip()
            try:
                kickoff = _time(candidate["kickoff"])
            except (ValueError, TypeError, KeyError, OverflowError):
                reasons["invalid_kickoff"] += 1
                continue
            if not fid or not league or not market:
                reasons["unknown_canonical_identity"] += 1
                continue
            if captured >= kickoff:
                reasons["post_kickoff_forecast"] += 1
                continue
            p = _probability(candidate.get("calibrated_probability"))
            conservative = _probability(candidate.get("conservative_probability"))
            if p is None or conservative is None:
                reasons["missing_captured_probabilities"] += 1
                continue
            key = (fid, league, market)
            if key not in first or captured < first[key]["captured"]:
                first[key] = {
                    "candidate": candidate, "captured": captured,
                    "kickoff": kickoff, "snapshot_id": snapshot["snapshot_id"],
                }

    observations = []
    for key, record in sorted(first.items()):
        fid, league, market = key
        finals = final_index.get((fid, league), [])
        if not finals:
            reasons["verified_final_missing"] += 1
            continue
        if len(finals) != 1:
            reasons["ambiguous_final"] += 1
            continue
        final = finals[0]
        if abs((_time(final["kickoff"]) - record["kickoff"]).total_seconds()) > MAX_KICKOFF_DRIFT_SECONDS:
            reasons["kickoff_identity_mismatch"] += 1
            continue
        y = _score_market(final["home_score"], final["away_score"], market)
        if y is None:
            reasons["unsupported_market_or_push"] += 1
            continue
        candidate = record["candidate"]
        odds = candidate.get("odds")
        try:
            odds = float(odds)
            if not isfinite(odds) or odds <= 1:
                odds = None
        except (ValueError, TypeError, OverflowError):
            odds = None
        observations.append({
            "fixture_id": fid, "league_slug": league, "market": market,
            "kickoff": record["kickoff"].isoformat(),
            "captured_at": record["captured"].isoformat(),
            "snapshot_id": record["snapshot_id"],
            "outcome": y,
            "calibrated_probability": candidate["calibrated_probability"],
            "conservative_probability": candidate["conservative_probability"],
            "bookmaker_probability": _probability(
                candidate.get("bookmaker_implied_probability")),
            "lower_bound": _probability(candidate.get("lower_reliability_bound")),
            "odds": odds if str(candidate.get("odds_source") or "").casefold() == "sportybet" else None,
            "bookable": candidate.get("bookable") is True,
            "originally_official_eligible": candidate.get("safe_tier_eligible") is True,
            "trust_grade": candidate.get("trust_grade"),
            "competition_type": candidate.get("competition_type") or "UNKNOWN",
            "source": final["source"],
            "source_event_id": final["source_event_id"],
        })
    return {
        "mode": "OFFLINE_SHADOW_ONLY",
        "observations": observations,
        "unique_pre_match_forecasts": len(first),
        "settled_unique_forecasts": len(observations),
        "pending_or_excluded": dict(sorted(reasons.items())),
        "upstream_score_verification_required": True,
    }


def _metrics(rows: list[dict], variant: str) -> dict:
    n = len(rows)
    if not n:
        return {"n": 0, "brier": None, "log_loss": None,
                "hit_rate": None, "priced_n": 0, "observed_return": None}
    probabilities = [r[variant] for r in rows]
    brier = sum((p - r["outcome"]) ** 2 for r, p in zip(rows, probabilities)) / n
    loss = -sum(r["outcome"] * log(max(p, 1e-8)) +
                (1 - r["outcome"]) * log(max(1 - p, 1e-8))
                for r, p in zip(rows, probabilities)) / n
    # Observed return is descriptive only, NOT proof of attainable ROI.
    priced = [r for r in rows if r.get("bookable") and r.get("odds")]
    # A priced observational cohort is not an actual placed ticket. DNB has
    # draw/push payoff and must not be evaluated with this binary win formula.
    value_candidates = [
        r for r in priced if not r["market"].startswith("dnb_")
        and r[variant] * r["odds"] >= 1.0
    ]
    return {
        "n": n, "brier": round(brier, 6), "log_loss": round(loss, 6),
        "hit_rate": round(sum(r["outcome"] for r in rows) / n, 6),
        "priced_n": len(priced),
        "observed_return": (round(sum(r["outcome"] * r["odds"]
                                      for r in priced) / len(priced), 6)
                            if priced else None),
        "positive_value_candidate_n": len(value_candidates),
        "value_candidate_observed_return": (
            round(sum(r["outcome"] * r["odds"]
                      for r in value_candidates) / len(value_candidates), 6)
            if value_candidates else None
        ),
        "not_actual_stakes_or_booked_codes": True,
    }


def compare_market_penalties(observations: list[dict]) -> dict:
    """Chronological, market-specific shadow; no training on test outcomes.

    The half-relaxation is a *counterfactual diagnostic*, not the exact
    production probability formula. Never tune or promote from its holdout.
    """
    by_market: dict[str, list[dict]] = defaultdict(list)
    for item in observations:
        p = _probability(item.get("calibrated_probability"))
        base = _probability(item.get("conservative_probability"))
        if p is None or base is None or type(item.get("outcome")) is not int:
            continue
        if item["outcome"] not in (0, 1):
            continue
        row = dict(item)
        row["baseline"] = base
        row["half_relaxation"] = base + .5 * max(0.0, p - base)
        row["calibrated"] = p
        by_market[str(row["market"])].append(row)

    reports = {}
    for market, market_rows in sorted(by_market.items()):
        market_rows.sort(key=lambda r: (r["kickoff"], r["fixture_id"]))
        dates = sorted({r["kickoff"][:10] for r in market_rows})
        # Keep all events from the same date in the same chronological fold.
        split = max(1, min(len(dates) - 1, int(len(dates) * .6)))
        holdout_start = dates[split] if len(dates) >= 2 else None
        holdout = [r for r in market_rows
                   if holdout_start and r["kickoff"][:10] >= holdout_start]
        ready = (len(holdout) >= MIN_MARKET_HOLDOUT and
                 len({r["kickoff"][:10] for r in holdout}) >= MIN_HOLDOUT_DAYS)
        metrics = {name: _metrics(holdout, name)
                   for name in ("baseline", "half_relaxation", "calibrated")}
        reports[market] = {
            "all_settled": len(market_rows), "holdout_start": holdout_start,
            "holdout_days": len({r["kickoff"][:10] for r in holdout}),
            "ready_for_review": ready,
            "methods": metrics,
            "half_relaxation_brier_delta": (
                round(metrics["baseline"]["brier"] -
                      metrics["half_relaxation"]["brier"], 6)
                if holdout else None),
            "action": "REVIEW_MANUALLY" if ready else "COLLECT_MORE_VERIFIED_LABELS",
        }
    return {
        "mode": "SHADOW_NO_POLICY_CHANGE", "markets": reports,
        "automatic_promotion": False,
        "warning": "No live probability, expected-value or trust gate changed; "
                   "holdout comparison is descriptive, not prospective ROI proof.",
    }


def independent_tier_exposure(product_legs: dict[str, list[dict]]) -> dict:
    """Measure exposure cost of six independently selected tier proposals.

    Do not fabricate alternative selections from a thin slate. This reports
    the capacity tradeoff before any selector or live publication changes.
    """
    uses = Counter()
    tiers = {}
    for product in PRODUCTS:
        legs = product_legs.get(product) or []
        ids = [str(p.get("fixture_id") or p.get("match_id") or "")
               for p in legs]
        valid = bool(ids) and all(ids) and len(ids) == len(set(ids))
        tiers[product] = {
            "independently_selected": bool(ids),
            "valid_unique_fixtures": valid,
            "fixtures": len(ids),
            "duplicate_in_same_slip": len(ids) - len(set(ids)),
        }
        if valid:
            uses.update(ids)
    shared = {fid: n for fid, n in sorted(uses.items()) if n > 1}
    return {
        "mode": "SHADOW_NO_PUBLICATION",
        "products": tiers, "cross_tier_shared_fixtures": shared,
        "max_fixture_exposure": max(uses.values(), default=0),
        "tiers_requiring_replacement_under_cap_1": sum(
            any(uses[fid] > 1 for fid in
                (str(p.get("fixture_id") or p.get("match_id") or "")
                 for p in product_legs.get(product) or []))
            for product in PRODUCTS
            if tiers[product]["valid_unique_fixtures"]
        ),
        "capacity_shadow": {
            str(cap): {
                "overexposed_fixtures": sum(n > cap for n in uses.values()),
                "excess_fixture_uses": sum(max(0, n - cap)
                                           for n in uses.values()),
            } for cap in (1, 2, 3)
        },
        "replacement_candidates_verified": False,
        "official_booking_verified": False,
    }


def settlement_queue_audit(queue: dict) -> dict:
    """Count review categories only. Pending never becomes won/lost here."""
    legs = queue.get("legs") or []
    overdue = [row for row in legs if row.get("overdue_48h") is True]
    return {
        "mode": "READ_ONLY_NO_SETTLEMENT",
        "reported_total_pending": queue.get("total_pending_legs"),
        "returned_pending": len(legs),
        "reported_overdue_48h": queue.get("overdue_48h"),
        "returned_overdue_48h": len(overdue),
        "unmapped_or_unknown": sum(
            row.get("review_category") in ("country_unknown", "source_unsupported")
            for row in overdue),
        "by_reason": dict(sorted(Counter(
            str(row.get("review_category") or "unknown") for row in overdue
        ).items())),
        "truncated": (isinstance(queue.get("total_pending_legs"), int)
                      and len(legs) < queue["total_pending_legs"]),
        "readiness": "NEEDS_INDEPENDENT_FINALS_AND_LIVE_DATABASE",
    }
