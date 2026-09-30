"""Offline-only exact linear feasibility check for the daily accumulator pool.

The selector's constraints are additive in log odds and log expected return,
so MILP can test the full eligible pool without enumerating every ticket.
This does not change production selection or its thresholds.
"""

import math
import itertools
from collections import Counter, defaultdict


def _feasible(picks, target, max_picks, min_ev, band_low=.8, band_high=1.45,
              market_cap=None, team_cap=None, max_leg_ev=1.04):
    import numpy as np
    from scipy.optimize import Bounds, LinearConstraint, milp
    from leagues.selection import (MARKET_CAP, TEAM_TO_SCORE_CAP, UNDER_CAP,
                                   exposure_group)
    from leagues.selection_quality import selection_probability

    n = len(picks)
    if not n:
        return {"feasible": False, "solver_status": "empty"}
    rows, low, high = [], [], []

    def add(values, lo, hi):
        rows.append(values)
        low.append(lo)
        high.append(hi)

    odds = np.array([math.log(float(p["odds"])) for p in picks])
    ev = np.array([math.log(float(p["odds"]) * selection_probability(p))
                   for p in picks])
    add(np.ones(n), 1, max_picks)
    add(odds, math.log(target * band_low), math.log(target * band_high))
    add(ev, math.log(min_ev), np.inf)
    add(ev - math.log(max_leg_ev), -np.inf, 0)
    groups = defaultdict(list)
    fixtures = defaultdict(list)
    exposures = defaultdict(list)
    unders = []
    for i, pick in enumerate(picks):
        fixtures[str(pick["match_id"])].append(i)
        groups[str(pick["market_group"])].append(i)
        exposures[exposure_group(pick["market_group"])].append(i)
        if str(pick.get("market", "")).startswith("under_"):
            unders.append(i)

    def cap(indexes, limit):
        values = np.zeros(n)
        values[indexes] = 1
        add(values, -np.inf, limit)

    for indexes in fixtures.values():
        cap(indexes, 1)
    for indexes in groups.values():
        cap(indexes, MARKET_CAP if market_cap is None else market_cap)
    if exposures.get("team_to_score"):
        cap(exposures["team_to_score"],
            TEAM_TO_SCORE_CAP if team_cap is None else team_cap)
    if UNDER_CAP is not None and unders:
        cap(unders, UNDER_CAP)

    result = milp(
        c=-odds, integrality=np.ones(n), bounds=Bounds(0, 1),
        constraints=LinearConstraint(np.array(rows), low, high),
        options={"time_limit": 30},
    )
    if result.status != 0:
        return {"feasible": False if result.status == 2 else None,
                "solver_status": str(result.message)}
    selected = [picks[i] for i, x in enumerate(result.x) if x > .5]
    actual_odds = math.prod(float(p["odds"]) for p in selected)
    actual_ev = math.prod(float(p["odds"]) * selection_probability(p)
                          for p in selected)
    return {"feasible": True, "solver_status": "optimal",
            "odds": round(actual_odds, 4), "expected_payout_factor": round(actual_ev, 5),
            "legs": [{"fixture_id": p["match_id"], "market": p["market"],
                      "odds": p["odds"]} for p in selected]}


def diagnose(picks, target=10.0, max_picks=10, min_confidence=.65,
             min_ev=.63):
    from leagues.selection import (MIN_USEFUL_ODDS, _bound_search_space,
                                   _cost, _stratify, select_accumulator,
                                   MARKET_CAP, TEAM_TO_SCORE_CAP, UNDER_CAP,
                                   exposure_group)
    from leagues.selection_quality import selection_probability

    confidence = [p for p in picks
                  if selection_probability(p) >= min_confidence]
    useful = [p for p in confidence if p["odds"] >= MIN_USEFUL_ODDS]
    grouped = {}
    for pick in sorted(useful, key=_cost):
        grouped.setdefault((pick["match_id"], pick["market_group"]), pick)
    full = sorted(grouped.values(), key=_cost)
    stratified = _stratify(full)
    bounded = _bound_search_space(stratified)
    production = select_accumulator(
        picks, target, max_picks, min_confidence, min_ev=min_ev,
        canonicalize=False)
    stratified_ids = {id(p) for p in stratified}
    bounded_ids = {id(p) for p in bounded}
    combo_counts = Counter()
    for size in range(1, min(max_picks, len(bounded)) + 1):
        for combo in itertools.combinations(bounded, size):
            combo_counts["considered"] += 1
            if len({p["match_id"] for p in combo}) != size:
                combo_counts["rejected_one_fixture"] += 1
                continue
            combo_counts["after_one_fixture"] += 1
            groups = Counter(p["market_group"] for p in combo)
            if max(groups.values()) > MARKET_CAP:
                combo_counts["rejected_market_cap"] += 1
                continue
            combo_counts["after_market_cap"] += 1
            team_count = sum(exposure_group(p["market_group"]) == "team_to_score"
                             for p in combo)
            if team_count > TEAM_TO_SCORE_CAP:
                combo_counts["rejected_team_to_score_cap"] += 1
                continue
            combo_counts["after_team_to_score_cap"] += 1
            if UNDER_CAP is not None and sum(str(p["market"]).startswith("under_")
                                             for p in combo) > UNDER_CAP:
                combo_counts["rejected_under_cap"] += 1
                continue
            combo_counts["after_under_cap"] += 1
            odds = math.prod(p["odds"] for p in combo)
            ev = math.prod(p["odds"] * selection_probability(p) for p in combo)
            if not target * .8 <= odds <= target * 1.45:
                combo_counts["rejected_target_band"] += 1
                continue
            combo_counts["after_target_band"] += 1
            if ev < min_ev:
                combo_counts["rejected_min_ev"] += 1
                continue
            combo_counts["after_min_ev"] += 1
            if ev ** (1 / size) > 1.04:
                combo_counts["rejected_geometric_ev"] += 1
                continue
            combo_counts["valid_in_band"] += 1
    return {
        "counts": {"canonical": len(picks), "above_confidence": len(confidence),
                   "above_useful_odds": len(useful),
                   "per_fixture_group": len(full), "stratified": len(stratified),
                   "bounded": len(bounded)},
        "full_pool": _feasible(full, target, max_picks, min_ev),
        "stratified_pool": _feasible(stratified, target, max_picks, min_ev),
        "bounded_pool": _feasible(bounded, target, max_picks, min_ev),
        "nominal_target": {
            "full_pool": _feasible(full, target, max_picks, min_ev, band_low=1.0),
            "stratified_pool": _feasible(stratified, target, max_picks, min_ev,
                                         band_low=1.0),
            "bounded_pool": _feasible(bounded, target, max_picks, min_ev,
                                      band_low=1.0),
        },
        "counterfactual_nominal": {
            "market_cap_plus_1": _feasible(full, target, max_picks, min_ev,
                                            band_low=1.0,
                                            market_cap=MARKET_CAP + 1),
            "team_to_score_plus_1": _feasible(full, target, max_picks, min_ev,
                                               band_low=1.0,
                                               team_cap=TEAM_TO_SCORE_CAP + 1),
            "max_legs_plus_1": _feasible(full, target, max_picks + 1, min_ev,
                                          band_low=1.0),
            "min_ev_relaxed": _feasible(full, target, max_picks, .50,
                                         band_low=1.0),
            "max_leg_ev_relaxed": _feasible(full, target, max_picks, min_ev,
                                             band_low=1.0, max_leg_ev=1.10),
        },
        "production_odds": production[1],
        "production_leg_count": len(production[0]),
        "dropped_by_stratification": [
            {"fixture_id": p["match_id"], "market": p["market"],
             "odds": p["odds"]} for p in full if id(p) not in stratified_ids],
        "dropped_by_bound": [
            {"fixture_id": p["match_id"], "market": p["market"],
             "odds": p["odds"]} for p in stratified if id(p) not in bounded_ids],
        "market_groups_full": dict(Counter(p["market_group"] for p in full)),
        "bounded_combination_funnel": dict(combo_counts),
    }
