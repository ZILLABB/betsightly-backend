"""One versioned capability and policy contract for football markets.

ACTIVE means eligible for the existing conditional trust/price gates, not an
unconditional instruction to publish. SHADOW/MAPPED_ONLY markets never enter
public selection. No model is promoted by changing this registry.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass

REGISTRY_VERSION = "market-registry-v1"


@dataclass(frozen=True)
class MarketSpec:
    key: str
    label: str
    group: str
    calibration_group: str | None
    model_sources: tuple[str, ...]
    ml_target: str | None
    ml_support: str  # DIRECT, DERIVED, NONE
    sportybet: tuple[str, str, str] | None
    settlement: bool
    replay: bool
    public_policy: str  # TRUSTED, EVIDENCE_ELIGIBLE, DEVELOPING, RESTRICTED, DISABLED
    evidence_policy: str  # PROMOTED, RESTRICTED, UNVALIDATED
    activation: str
    builder: bool
    safe_tier: bool
    booking: bool
    can_void: bool
    exposure: str
    candidate_generation: bool


def _spec(key: str, label: str, group: str, calibration: str | None,
          sportybet: tuple[str, str, str], *, public: str = "RESTRICTED",
          evidence: str = "RESTRICTED", activation: str = "RESTRICTED",
          ml_target: str | None = None, ml: str = "NONE",
          modeled: bool = True, replay: bool = True,
          safe: bool = False, can_void: bool = False,
          candidate_generation: bool = True) -> MarketSpec:
    sources = (("base_poisson", "elo") if group in
               {"match_result", "double_chance", "dnb"} else
               ("base_poisson",)) if modeled else ()
    return MarketSpec(
        key, label, group, calibration, sources, ml_target, ml, sportybet,
        True, replay, public, evidence, activation,
        activation == "ACTIVE", safe and activation == "ACTIVE",
        activation == "ACTIVE", can_void,
        "team_to_score" if group.startswith("team_goals") else group,
        candidate_generation,
    )


_ROWS = (
    _spec("home_win", "{home} Win", "match_result", "match_result", ("1", "", "1"),
          public="EVIDENCE_ELIGIBLE", evidence="PROMOTED", activation="ACTIVE",
          ml_target="match_result", ml="DIRECT"),
    _spec("draw", "Draw", "match_result", "match_result", ("1", "", "2"),
          ml_target="match_result", ml="DIRECT"),
    _spec("away_win", "{away} Win", "match_result", "match_result", ("1", "", "3"),
          public="EVIDENCE_ELIGIBLE", evidence="PROMOTED", activation="ACTIVE",
          ml_target="match_result", ml="DIRECT"),
    _spec("home_or_draw", "{home} or Draw", "double_chance", "double_chance", ("10", "", "9"),
          public="TRUSTED", evidence="PROMOTED", activation="ACTIVE", safe=True,
          ml_target="match_result", ml="DERIVED"),
    _spec("home_or_away", "{home} or {away}", "double_chance", "double_chance", ("10", "", "10"),
          public="DISABLED", evidence="PROMOTED", activation="DISABLED"),
    _spec("away_or_draw", "{away} or Draw", "double_chance", "double_chance", ("10", "", "11"),
          public="TRUSTED", evidence="PROMOTED", activation="ACTIVE", safe=True,
          ml_target="match_result", ml="DERIVED"),
    _spec("dnb_home", "{home} (Draw No Bet)", "dnb", "dnb", ("11", "", "4"),
          public="TRUSTED", evidence="PROMOTED", activation="ACTIVE", safe=True,
          can_void=True),
    _spec("dnb_away", "{away} (Draw No Bet)", "dnb", "dnb", ("11", "", "5"),
          public="TRUSTED", evidence="PROMOTED", activation="ACTIVE", safe=True,
          can_void=True),
    _spec("over_1_5", "Over 1.5 Goals", "goals", "goals_over_1_5", ("18", "total=1.5", "12"),
          public="TRUSTED", evidence="PROMOTED", activation="ACTIVE", safe=True,
          ml_target="over_1_5", ml="DIRECT"),
    _spec("under_1_5", "Under 1.5 Goals", "goals", "goals_under_1_5", ("18", "total=1.5", "13"),
          public="DISABLED", activation="DISABLED"),
    _spec("over_2_5", "Over 2.5 Goals", "goals", "goals_over_2_5", ("18", "total=2.5", "12"),
          public="DEVELOPING", evidence="PROMOTED", activation="ACTIVE",
          ml_target="over_2_5", ml="DIRECT"),
    _spec("under_2_5", "Under 2.5 Goals", "goals", "goals_under_2_5", ("18", "total=2.5", "13"),
          ml_target="over_2_5", ml="DERIVED"),
    _spec("over_3_5", "Over 3.5 Goals", "goals", "goals_over_3_5", ("18", "total=3.5", "12"),
          public="DISABLED", activation="DISABLED"),
    _spec("under_3_5", "Under 3.5 Goals", "goals", "goals_under_3_5", ("18", "total=3.5", "13"),
          activation="SHADOW"),
    _spec("over_4_5", "Over 4.5 Goals", "goals", "goals_over_4_5", ("18", "total=4.5", "12"),
          activation="SHADOW",
          candidate_generation=False),
    _spec("under_4_5", "Under 4.5 Goals", "goals", "goals_under_4_5", ("18", "total=4.5", "13"),
          public="TRUSTED", evidence="PROMOTED", activation="ACTIVE", safe=True),
    _spec("home_over_0_5", "{home} to Score", "team_goals_home", "team_goals_home", ("19", "total=0.5", "12"),
          public="DEVELOPING", evidence="PROMOTED", activation="ACTIVE"),
    _spec("home_under_0_5", "{home} Under 0.5 Goals", "team_goals_home", "team_goals_home_under_0_5", ("19", "total=0.5", "13"),
          activation="SHADOW",
          candidate_generation=False),
    _spec("home_over_1_5", "{home} Over 1.5 Goals", "team_goals_home", "team_goals_home", ("19", "total=1.5", "12"),
          evidence="PROMOTED"),
    _spec("home_under_1_5", "{home} Under 1.5 Goals", "team_goals_home", "team_goals_home_under_1_5", ("19", "total=1.5", "13"),
          activation="SHADOW",
          candidate_generation=False),
    _spec("away_over_0_5", "{away} to Score", "team_goals_away", "team_goals_away", ("20", "total=0.5", "12"),
          public="DEVELOPING", evidence="PROMOTED", activation="ACTIVE"),
    _spec("away_under_0_5", "{away} Under 0.5 Goals", "team_goals_away", "team_goals_away_under_0_5", ("20", "total=0.5", "13"),
          activation="SHADOW",
          candidate_generation=False),
    _spec("away_over_1_5", "{away} Over 1.5 Goals", "team_goals_away", "team_goals_away", ("20", "total=1.5", "12"),
          evidence="PROMOTED"),
    _spec("away_under_1_5", "{away} Under 1.5 Goals", "team_goals_away", "team_goals_away_under_1_5", ("20", "total=1.5", "13"),
          activation="SHADOW",
          candidate_generation=False),
    _spec("btts_yes", "Both Teams to Score", "btts", "btts_yes", ("29", "", "74")),
    _spec("btts_no", "Both Teams to Score - No", "btts", "btts_no", ("29", "", "76")),
)

MARKETS = {spec.key: spec for spec in _ROWS}
if len(MARKETS) != len(_ROWS):
    raise ValueError("duplicate market key in registry")

MARKET_LABELS = {key: spec.label for key, spec in MARKETS.items() if spec.model_sources}
MARKET_GROUP = {key: spec.group for key, spec in MARKETS.items() if spec.model_sources}
CALIBRATION_GROUP = {key: spec.calibration_group for key, spec in MARKETS.items()
                     if spec.model_sources}
REAL_ODDS_KEY = {key: key for key, spec in MARKETS.items() if spec.model_sources}
MARKET_TO_SPORTYBET = {key: spec.sportybet for key, spec in MARKETS.items()
                       if spec.sportybet}
FIXED_SPORTYBET = {}
LINE_SPORTYBET = {}
for key, mapping in MARKET_TO_SPORTYBET.items():
    market_id, specifier, outcome_id = mapping
    if not specifier:
        FIXED_SPORTYBET.setdefault(market_id, {})[outcome_id] = key
    else:
        LINE_SPORTYBET.setdefault(market_id, {}).setdefault(specifier, {})[outcome_id] = key
OVER_UNDER_SPORTYBET = {
    market_id: {specifier: (outcomes["12"], outcomes["13"])
                for specifier, outcomes in lines.items()}
    for market_id, lines in LINE_SPORTYBET.items()
}


def capability_matrix() -> list[dict]:
    """Stable, machine-readable diagnostic; no providers or models are loaded."""
    rows = []
    for spec in MARKETS.values():
        row = asdict(spec)
        row.update(predictor=bool(spec.model_sources),
                   direct_ml=spec.ml_support == "DIRECT",
                   derived_ml=spec.ml_support == "DERIVED",
                   poisson="base_poisson" in spec.model_sources,
                   elo="elo" in spec.model_sources,
                   sportybet_mapped=bool(spec.sportybet),
                   exact_booking=spec.booking,
                   public=spec.activation == "ACTIVE",
                   banker=spec.safe_tier,
                   two_odds=spec.safe_tier,
                   five_odds=spec.builder,
                   ten_odds=spec.builder,
                   rollover=spec.safe_tier)
        rows.append(row)
    return rows


if __name__ == "__main__":
    print(json.dumps({"version": REGISTRY_VERSION,
                      "markets": capability_matrix()}, indent=2))
