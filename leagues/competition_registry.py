"""Authoritative metadata for every fixture competition BetSightly enables.

Provider identifiers in this module are enabled only after the ESPN scoreboard
returned a competition identity and usable scheduled or historical events.
Consumers should derive their slug/name maps from this registry rather than
maintaining parallel lists.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import re


@dataclass(frozen=True)
class Competition:
    slug: str
    display_name: str
    region: str
    country: str | None = None
    competition_type: str = "LEAGUE"
    team_type: str = "CLUB"
    format: str = "LEAGUE"
    supports_draw: bool = True
    possible_neutral_venue: bool = False
    possible_extra_time: bool = False
    possible_penalties: bool = False
    possible_two_leg_tie: bool = False
    priority: int = 50
    enabled: bool = True
    provider_verified: bool = True
    known_limitations: str | None = None

    def public_dict(self) -> dict:
        return asdict(self)


def _league(slug: str, name: str, region: str, country: str | None = None,
            priority: int = 50) -> Competition:
    return Competition(slug, name, region, country, priority=priority)


def _cup(slug: str, name: str, region: str, country: str,
         priority: int = 60) -> Competition:
    return Competition(
        slug, name, region, country, "DOMESTIC_CUP", "CLUB", "KNOCKOUT",
        possible_neutral_venue=True, possible_extra_time=True,
        possible_penalties=True, possible_two_leg_tie=True, priority=priority,
    )


_DOMESTIC_LEAGUES = [
    # Europe
    _league("eng.1", "Premier League", "Europe", "England", 90),
    _league("eng.2", "EFL Championship", "Europe", "England", 75),
    _league("eng.3", "EFL League One", "Europe", "England"),
    _league("eng.4", "EFL League Two", "Europe", "England"),
    _league("esp.1", "LaLiga", "Europe", "Spain", 90),
    _league("esp.2", "LaLiga 2", "Europe", "Spain", 70),
    _league("ger.1", "Bundesliga", "Europe", "Germany", 90),
    _league("ger.2", "2. Bundesliga", "Europe", "Germany", 70),
    _league("ita.1", "Serie A", "Europe", "Italy", 90),
    _league("ita.2", "Serie B", "Europe", "Italy", 70),
    _league("fra.1", "Ligue 1", "Europe", "France", 90),
    _league("fra.2", "Ligue 2", "Europe", "France", 70),
    _league("por.1", "Primeira Liga", "Europe", "Portugal", 75),
    _league("ned.1", "Eredivisie", "Europe", "Netherlands", 75),
    _league("bel.1", "Belgian Pro League", "Europe", "Belgium", 70),
    _league("tur.1", "Süper Lig", "Europe", "Turkey", 70),
    _league("sui.1", "Swiss Super League", "Europe", "Switzerland"),
    _league("aut.1", "Austrian Bundesliga", "Europe", "Austria"),
    _league("gre.1", "Greek Super League", "Europe", "Greece"),
    _league("sco.1", "Scottish Premiership", "Europe", "Scotland", 65),
    _league("sco.2", "Scottish Championship", "Europe", "Scotland"),
    _league("den.1", "Danish Superliga", "Europe", "Denmark"),
    _league("nor.1", "Eliteserien", "Europe", "Norway"),
    _league("swe.1", "Allsvenskan", "Europe", "Sweden"),
    _league("fin.1", "Veikkausliiga", "Europe", "Finland"),
    _league("irl.1", "League of Ireland", "Europe", "Ireland"),
    _league("pol.1", "Ekstraklasa", "Europe", "Poland"),
    _league("cze.1", "Czech First League", "Europe", "Czechia"),
    _league("rou.1", "Liga I", "Europe", "Romania"),
    _league("rus.1", "Russian Premier League", "Europe", "Russia"),
    _league("ukr.1", "Ukrainian Premier League", "Europe", "Ukraine"),
    _league("cro.1", "HNL", "Europe", "Croatia"),
    _league("srb.1", "Serbian SuperLiga", "Europe", "Serbia"),
    _league("hun.1", "NB I", "Europe", "Hungary"),
    _league("isr.1", "Ligat ha'Al", "Europe", "Israel"),
    # Americas
    _league("usa.1", "MLS", "North America", "United States", 75),
    _league("usa.nwsl", "NWSL", "North America", "United States", 65),
    _league("usa.usl.1", "USL Championship", "North America", "United States"),
    _league("mex.1", "Liga MX", "North America", "Mexico", 75),
    _league("mex.2", "Liga de Expansión MX", "North America", "Mexico"),
    _league("can.1", "Canadian Premier League", "North America", "Canada"),
    _league("crc.1", "Liga Promerica", "North America", "Costa Rica"),
    _league("gua.1", "Liga Nacional Guatemala", "North America", "Guatemala"),
    _league("hon.1", "Liga Nacional Honduras", "North America", "Honduras"),
    _league("slv.1", "Primera División El Salvador", "North America", "El Salvador"),
    _league("pan.1", "LPF Panamá", "North America", "Panama"),
    _league("jam.1", "Jamaica Premier League", "North America", "Jamaica"),
    _league("bra.1", "Brasileirão Série A", "South America", "Brazil", 80),
    _league("bra.2", "Brasileirão Série B", "South America", "Brazil", 65),
    _league("arg.1", "Liga Profesional Argentina", "South America", "Argentina", 80),
    _league("arg.2", "Primera Nacional", "South America", "Argentina"),
    _league("chi.1", "Primera División Chile", "South America", "Chile"),
    _league("col.1", "Categoría Primera A", "South America", "Colombia", 65),
    _league("per.1", "Liga 1 Perú", "South America", "Peru"),
    _league("uru.1", "Primera División Uruguay", "South America", "Uruguay"),
    _league("ecu.1", "LigaPro Ecuador", "South America", "Ecuador"),
    _league("par.1", "División Profesional Paraguay", "South America", "Paraguay"),
    _league("bol.1", "División Profesional Bolivia", "South America", "Bolivia"),
    _league("ven.1", "Primera División Venezuela", "South America", "Venezuela"),
    # Asia/Oceania/Africa
    _league("jpn.1", "J1 League", "Asia", "Japan", 65),
    _league("jpn.2", "J2 League", "Asia", "Japan"),
    _league("kor.1", "K League 1", "Asia", "South Korea"),
    _league("chn.1", "Chinese Super League", "Asia", "China"),
    _league("aus.1", "A-League", "Oceania", "Australia", 65),
    _league("idn.1", "Liga 1 Indonesia", "Asia", "Indonesia"),
    _league("tha.1", "Thai League 1", "Asia", "Thailand"),
    _league("ind.1", "Indian Super League", "Asia", "India"),
    _league("mys.1", "Malaysia Super League", "Asia", "Malaysia"),
    _league("qat.1", "Qatar Stars League", "Asia", "Qatar"),
    _league("sau.1", "Saudi Pro League", "Asia", "Saudi Arabia", 70),
    _league("uae.1", "UAE Pro League", "Asia", "United Arab Emirates"),
    _league("irn.1", "Persian Gulf Pro League", "Asia", "Iran"),
    _league("rsa.1", "South African Premiership", "Africa", "South Africa", 70),
    _league("egy.1", "Egyptian Premier League", "Africa", "Egypt", 70),
    _league("mar.1", "Botola Pro", "Africa", "Morocco", 65),
    _league("tun.1", "Tunisian Ligue 1", "Africa", "Tunisia"),
    _league("alg.1", "Algerian Ligue 1", "Africa", "Algeria"),
    _league("nga.1", "Nigeria Premier League", "Africa", "Nigeria", 70),
    _league("gha.1", "Ghana Premier League", "Africa", "Ghana", 65),
]

_DOMESTIC_CUPS = [
    _cup("eng.fa", "FA Cup", "Europe", "England", 80),
    _cup("eng.league_cup", "Carabao Cup", "Europe", "England", 75),
    _cup("esp.copa_del_rey", "Copa del Rey", "Europe", "Spain", 80),
    _cup("ger.dfb_pokal", "DFB Pokal", "Europe", "Germany", 80),
    _cup("ita.coppa_italia", "Coppa Italia", "Europe", "Italy", 80),
    _cup("fra.coupe_de_france", "Coupe de France", "Europe", "France", 75),
    _cup("por.taca.portugal", "Taca de Portugal", "Europe", "Portugal", 70),
    _cup("ned.cup", "Dutch KNVB Beker", "Europe", "Netherlands", 70),
    _cup("sco.tennents", "Scottish Cup", "Europe", "Scotland", 65),
]


def _continental(slug: str, name: str, region: str, priority: int = 80,
                 two_leg: bool = True) -> Competition:
    return Competition(
        slug, name, region, competition_type="CONTINENTAL_CLUB", team_type="CLUB",
        format="MIXED", possible_neutral_venue=True, possible_extra_time=True,
        possible_penalties=True, possible_two_leg_tie=two_leg, priority=priority,
    )


def _international(slug: str, name: str, region: str, kind: str,
                   fmt: str = "MIXED", priority: int = 75) -> Competition:
    knockout = fmt in {"KNOCKOUT", "MIXED"} and kind == "INTERNATIONAL_TOURNAMENT"
    return Competition(
        slug, name, region, competition_type=kind, team_type="NATIONAL", format=fmt,
        possible_neutral_venue=kind == "INTERNATIONAL_TOURNAMENT",
        possible_extra_time=knockout, possible_penalties=knockout,
        possible_two_leg_tie=kind == "INTERNATIONAL_QUALIFIER", priority=priority,
    )


_TOURNAMENTS = [
    _continental("uefa.champions", "UEFA Champions League", "Europe", 100),
    _continental("uefa.europa", "UEFA Europa League", "Europe", 90),
    _continental("uefa.europa.conf", "UEFA Conference League", "Europe", 80),
    _continental("uefa.super_cup", "UEFA Super Cup", "Europe", 80, False),
    _continental("conmebol.libertadores", "Copa Libertadores", "South America", 90),
    _continental("conmebol.sudamericana", "Copa Sudamericana", "South America", 80),
    _continental("concacaf.champions", "CONCACAF Champions Cup", "North America", 80),
    _continental("caf.champions", "CAF Champions League", "Africa", 85),
    _continental("caf.confed", "CAF Confederation Cup", "Africa", 75),
    _continental("afc.champions", "AFC Champions League Elite", "Asia", 85),
    _continental("afc.cup", "AFC Champions League Two", "Asia", 70),
    _international("fifa.world", "FIFA World Cup", "Global", "INTERNATIONAL_TOURNAMENT", priority=100),
    _international("uefa.euro", "UEFA European Championship", "Europe", "INTERNATIONAL_TOURNAMENT", priority=95),
    _international("uefa.nations", "UEFA Nations League", "Europe", "INTERNATIONAL_TOURNAMENT", priority=85),
    _international("caf.nations", "Africa Cup of Nations", "Africa", "INTERNATIONAL_TOURNAMENT", priority=95),
    _international("conmebol.america", "Copa América", "South America", "INTERNATIONAL_TOURNAMENT", priority=95),
    _international("concacaf.gold", "Concacaf Gold Cup", "North America", "INTERNATIONAL_TOURNAMENT", priority=85),
    _international("afc.asian.cup", "AFC Asian Cup", "Asia", "INTERNATIONAL_TOURNAMENT", priority=90),
    _international("uefa.euroq", "UEFA European Championship Qualifying", "Europe", "INTERNATIONAL_QUALIFIER", "GROUP_STAGE", 85),
    _international("fifa.worldq.uefa", "World Cup Qualifying — UEFA", "Europe", "INTERNATIONAL_QUALIFIER", "MIXED", 90),
    _international("fifa.worldq.caf", "World Cup Qualifying — CAF", "Africa", "INTERNATIONAL_QUALIFIER", "MIXED", 95),
    _international("fifa.worldq.concacaf", "World Cup Qualifying — Concacaf", "North America", "INTERNATIONAL_QUALIFIER", "MIXED", 85),
    _international("fifa.worldq.afc", "World Cup Qualifying — AFC", "Asia", "INTERNATIONAL_QUALIFIER", "MIXED", 85),
    _international("fifa.worldq.conmebol", "World Cup Qualifying — CONMEBOL", "South America", "INTERNATIONAL_QUALIFIER", "LEAGUE", 90),
    _international("fifa.worldq.ofc", "World Cup Qualifying — OFC", "Oceania", "INTERNATIONAL_QUALIFIER", "MIXED", 65),
    _international("caf.nations_qual", "Africa Cup of Nations Qualifying", "Africa", "INTERNATIONAL_QUALIFIER", "GROUP_STAGE", 90),
    _international("fifa.friendly", "International Friendly", "Global", "INTERNATIONAL_FRIENDLY", "LEAGUE", 40),
    Competition("club.friendly", "Club Friendly", "Global", competition_type="LEAGUE",
                team_type="CLUB", format="LEAGUE", priority=20,
                known_limitations="Friendly line-ups and motivation are volatile."),
]

COMPETITIONS: dict[str, Competition] = {
    item.slug: item for item in [*_DOMESTIC_LEAGUES, *_DOMESTIC_CUPS, *_TOURNAMENTS]
}
if len(COMPETITIONS) != len(_DOMESTIC_LEAGUES) + len(_DOMESTIC_CUPS) + len(_TOURNAMENTS):
    raise RuntimeError("competition registry contains duplicate provider slugs")

# Explicitly audited but not enabled: no usable ESPN competition payload was
# returned for the tested historical windows.
UNAVAILABLE_COMPETITIONS = {
    "ofc.nations": "ESPN scoreboard returned no competition identity or events.",
    "caf.super": "No verifiable ESPN CAF Super Cup feed was returned.",
}


def competition_for(slug: str) -> Competition | None:
    return COMPETITIONS.get(slug)


def enabled_competitions() -> dict[str, Competition]:
    return {slug: item for slug, item in COMPETITIONS.items() if item.enabled}


def provider_slugs() -> dict[str, str]:
    return {slug: item.display_name for slug, item in enabled_competitions().items()}


def prior_keys(slug: str) -> list[str]:
    item = competition_for(slug)
    if not item:
        return ["global"]
    return [
        f"region_type:{item.region}|{item.competition_type}",
        f"competition_type:{item.competition_type}",
        f"team_type:{item.team_type}",
        "global",
    ]


_KNOCKOUT_WORDS = ("final", "semi", "quarter", "round-of", "round of", "playoff", "knockout")


def tournament_context(slug: str, event: dict, competition: dict) -> dict:
    """Extract conservative tournament context from ESPN's public payload."""
    meta = competition_for(slug)
    season = event.get("season") or {}
    stage_slug = str(season.get("slug") or "").strip()
    alt_note = str(competition.get("altGameNote") or "").strip()
    notes = " | ".join(
        str(n.get("headline") or n.get("text") or "")
        for n in (competition.get("notes") or []) if isinstance(n, dict)
    )
    text = " | ".join(v for v in (alt_note, notes) if v)
    stage = stage_slug.replace("-", " ").title() if stage_slug else None
    if not stage and "," in alt_note:
        stage = alt_note.rsplit(",", 1)[-1].strip()
    leg_match = re.search(r"\b([12])(?:st|nd)\s+Leg\b", text, re.I)
    leg_number = int(leg_match.group(1)) if leg_match else None
    aggregate = None
    aggregate_match = re.search(r"(\d+)\s*[-–]\s*(\d+)\s+on aggregate", text, re.I)
    if not aggregate_match:
        aggregate_match = re.search(r"aggregate(?:\s+tied)?\s*[: -]?\s*(\d+)\s*[-–]\s*(\d+)", text, re.I)
    if aggregate_match:
        aggregate = {"home": int(aggregate_match.group(1)),
                     "away": int(aggregate_match.group(2)), "source": "provider_note"}
    group_match = re.search(r"\bGroup\s+([A-Z0-9]+)\b", text, re.I)
    matchday_match = re.search(r"\bMatchday\s+(\d+)\b", text, re.I)
    knockout = bool(stage_slug and any(word in stage_slug for word in _KNOCKOUT_WORDS))
    knockout = knockout or bool(meta and meta.format == "KNOCKOUT") or leg_number is not None
    explicit_neutral = competition.get("neutralSite")
    inferred_neutral = bool(
        meta and meta.possible_neutral_venue and
        ((meta.team_type == "NATIONAL" and meta.competition_type == "INTERNATIONAL_TOURNAMENT")
         or stage_slug == "final" or "super cup" in meta.display_name.lower())
    )
    neutral = bool(explicit_neutral) if explicit_neutral is not None else inferred_neutral
    context_bits = []
    if stage:
        context_bits.append(stage)
    if leg_number:
        context_bits.append(f"{leg_number}{'st' if leg_number == 1 else 'nd'} leg")
    return {
        "competition_slug": slug,
        "competition_name": meta.display_name if meta else None,
        "competition_type": meta.competition_type if meta else None,
        "region": meta.region if meta else None,
        "team_type": meta.team_type if meta else None,
        "format": meta.format if meta else None,
        "stage": stage,
        "stage_slug": stage_slug or None,
        "round": stage,
        "group": group_match.group(1).upper() if group_match else None,
        "matchday": int(matchday_match.group(1)) if matchday_match else None,
        "leg_number": leg_number,
        "first_leg": leg_number == 1,
        "second_leg": leg_number == 2,
        "aggregate_score": aggregate,
        "aggregate_score_before": (
            aggregate if leg_number == 2 and
            not ((competition.get("status") or {}).get("type") or {}).get("completed")
            else None
        ),
        "qualification_state": (
            "TIED" if aggregate and aggregate["home"] == aggregate["away"]
            else "HOME_AHEAD" if aggregate and aggregate["home"] > aggregate["away"]
            else "AWAY_AHEAD" if aggregate else None
        ),
        "knockout": knockout,
        "neutral_venue": neutral,
        "final": stage_slug == "final",
        "semi_final": "semifinal" in stage_slug,
        "quarter_final": "quarterfinal" in stage_slug,
        "round_of_16": "round-of-16" in stage_slug,
        "qualifier": bool(meta and meta.competition_type == "INTERNATIONAL_QUALIFIER"),
        "playoff": "playoff" in stage_slug,
        "context_label": " · ".join(context_bits) or None,
        "provider_note": text or None,
    }


def regulation_score(competition: dict) -> dict:
    """Return 90-minute, extra-time and shootout scores from an ESPN event.

    ESPN's competitor score includes extra time but keeps shootout scores in a
    separate field. For AET/PEN games, regulation goals are reconstructed from
    scoring plays whose displayed minute is at most 90 (including 90+N).
    """
    competitors = competition.get("competitors") or []
    home = next((t for t in competitors if t.get("homeAway") == "home"), None)
    away = next((t for t in competitors if t.get("homeAway") == "away"), None)
    if not home or not away:
        return {}
    try:
        final_home, final_away = int(home.get("score", 0)), int(away.get("score", 0))
    except (TypeError, ValueError):
        return {}
    status = ((competition.get("status") or {}).get("type") or {}).get("name", "")
    went_beyond_90 = status in {"STATUS_FINAL_AET", "STATUS_FINAL_PEN"}
    regulation_home, regulation_away = final_home, final_away
    if went_beyond_90:
        regulation_home = regulation_away = 0
        home_id = str((home.get("team") or {}).get("id") or "")
        away_id = str((away.get("team") or {}).get("id") or "")
        scoring_details = [
            detail for detail in (competition.get("details") or [])
            if detail.get("scoringPlay") and not detail.get("shootout")
        ]
        if final_home + final_away and not scoring_details:
            return {}
        for detail in scoring_details:
            display = str((detail.get("clock") or {}).get("displayValue") or "")
            minute_match = re.match(r"(\d+)", display)
            minute = int(minute_match.group(1)) if minute_match else 999
            if minute > 90:
                continue
            team_id = str((detail.get("team") or {}).get("id") or "")
            if team_id == home_id:
                regulation_home += int(detail.get("scoreValue") or 1)
            elif team_id == away_id:
                regulation_away += int(detail.get("scoreValue") or 1)
    return {
        "home_score": regulation_home,
        "away_score": regulation_away,
        "score_90": {"home": regulation_home, "away": regulation_away},
        "score_extra_time": ({"home": final_home - regulation_home,
                              "away": final_away - regulation_away}
                             if went_beyond_90 else None),
        "penalty_score": ({"home": int(home.get("shootoutScore") or 0),
                           "away": int(away.get("shootoutScore") or 0)}
                          if status == "STATUS_FINAL_PEN" else None),
        "qualified_team": ((home.get("team") or {}).get("displayName") if home.get("winner")
                           else (away.get("team") or {}).get("displayName") if away.get("winner")
                           else None),
        "match_status": status,
    }
