"""Auditable incident evidence for verified finals absent from settlement feeds.

Records here are strictly limited to a reviewed fixture/date/event ID. They
must be supported by a federation or club match report, not by a prediction or
a bookmaker's live odds. Keep the source URL in each persisted settlement.
Do not apply these records to an event merely because its teams look similar.

This recovery covers individually verified fixtures from October 2026; it is not
a substitute for adding wider first-party score-provider coverage.
"""
from __future__ import annotations

from datetime import datetime, timezone

# Exact SportyBet IDs are from the immutable 14–16 October Rollover receipts.
# Each source independently confirms the 90-minute full-time score.
_VERIFIED_FINALS = (
    {
        "sportybet_event_id": "sr:match:73835212",
        "home": "Al-Taawoun FC", "away": "Al Rayyan SC",
        "date": "2026-10-14", "home_score": 2, "away_score": 1,
        "evidence_url": "https://www.the-afc.com/en/club/afc_champions_league_two.html/news/group-c-al-taawoun-fc-ksa-2-1-al-rayyan-sc-qat",
    },
    {
        "sportybet_event_id": "sr:match:75339776",
        "home": "Bohemians Prague 1905", "away": "FK Mlada Boleslav",
        "date": "2026-10-14", "home_score": 1, "away_score": 0,
        "evidence_url": "https://bohemians.cz/zapasy/MUZ/",
    },
    {
        "sportybet_event_id": "sr:match:73835214",
        "home": "AL Faisaly (Jor)", "away": "Al Nahda",
        "date": "2026-10-14", "home_score": 2, "away_score": 0,
        "evidence_url": "https://www.the-afc.com/en/club/afc_champions_league_two.html/news/group-c-al-faisaly-jor-x-x-al-nahda-oma-1",
    },
    # Official club match reports for UEFA Conference League round 1,
    # Thursday 15 October 2026. SportyBet IDs and kickoff dates are taken
    # from the *already published* Rollover Day 1 record.
    {
        "sportybet_event_id": "sr:match:74173148",
        "home": "Gent", "away": "AGF Aarhus",
        "date": "2026-10-15", "home_score": 1, "away_score": 0,
        "evidence_url": "https://www.kaagent.be/nl/nieuws/15-10-2026/te-lang-gewacht-om-onszelf-te-belonen",
    },
    {
        "sportybet_event_id": "sr:match:74173204",
        "home": "Freiburg", "away": "FK Jablonec",
        "date": "2026-10-15", "home_score": 3, "away_score": 2,
        "evidence_url": "https://www.scfreiburg.com/en/latest/first-team/match-reports/2026-27/sc-make-winning-start-to-league-phase/",
    },
    {
        "sportybet_event_id": "sr:match:74173182",
        "home": "Brighton", "away": "FK Kauno Zalgiris",
        "date": "2026-10-15", "home_score": 4, "away_score": 0,
        "evidence_url": "https://www.uefa.com/uefaconferenceleague/clubs/2605907/matches/",
    },
    # Friday 16 October 2026 — four already published manual Rollover
    # Day 2 legs. All reports below are official clubs/competition, reviewed
    # against the immutable SportyBet event IDs in wc_rollover_days id 935.
    # One leg finished 0-0 and is an actual loss (Over 1.5); never erase it.
    {
        "sportybet_event_id": "sr:match:72587358",
        "home": "MFK Karvina", "away": "Dukla Prague",
        "date": "2026-10-16", "home_score": 3, "away_score": 0,
        "evidence_url": "https://fkdukla.cz/match/9795",
    },
    {
        "sportybet_event_id": "sr:match:72300830",
        "home": "SFC Opava", "away": "FC Vysocina Jihlava",
        "date": "2026-10-16", "home_score": 1, "away_score": 3,
        "evidence_url": "https://www.fcvysocina.cz/match/8835-Vysocina-v-Opave-otocila-skore-cistym-hattrickem-Tyrese-Omotoyeho",
    },
    {
        "sportybet_event_id": "sr:match:73068120",
        "home": "FC Cartagena", "away": "CE Europa",
        "date": "2026-10-16", "home_score": 3, "away_score": 0,
        "evidence_url": "https://www.fccartagena.es/noticias/el-cartagena-vence-por-3-0-al-europa-en-el-fortin-albinegro",
    },
    {
        "sportybet_event_id": "sr:match:72043206",
        "home": "Widzew Lodz", "away": "Wisla Krakow",
        "date": "2026-10-16", "home_score": 0, "away_score": 0,
        "evidence_url": "https://ekstraklasa.org/en/schedule/2026-2027/round-11/",
    },
    # Wednesday 21 October 2026 — UEFA official matchday 3 regulation-time
    # finals. Bookmaker IDs and teams are from immutable production editorial
    # records; official competition's results table corroborates each score.
    # This is a ONE-TIME recovery for already-published slips, not a substitute
    # for the continuous live fixture identity + FT reconciliation pipeline.
    # The source URL is evidence, not an assertion of automated API rights.
    *(
        {
            "sportybet_event_id": event, "home": home, "away": away,
            "date": "2026-10-21", "home_score": hs, "away_score": vs,
            "evidence_url": (
                "https://www.uefa.com/uefachampionsleague/news/"
                "02a8-2174c9e9019d-f909a77bd77a-1000--2026-27-champions-"
                "league-all-the-league-phase-fixtures-a/"
            ),
        }
        for event, home, away, hs, vs in (
            ("sr:match:74165958", "Como 1907", "Man Utd", 4, 1),
            ("sr:match:74165972", "Betis", "Feyenoord", 1, 0),
            ("sr:match:74165968", "Inter", "Shakhtar D", 1, 0),
            ("sr:match:74165960", "Lille", "Galatasaray Istanbul", 2, 4),
            ("sr:match:74165974", "Sporting", "LASK Linz", 2, 3),
        )
    ),
    # Tuesday 27 October 2026 — verified from actual club/federation
    # reports, mapped to immutable production editorial SportyBet event IDs.
    # These one-time receipts repair the current manual backlog; they do not
    # imply that future matches in these leagues have automatic coverage.
    {
        "sportybet_event_id": "sr:match:68214868",
        "home": "FCI Levadia Tallinn", "away": "Tartu JK Tammeka",
        "date": "2026-10-27", "home_score": 2, "away_score": 1,
        "evidence_url": "https://fcilevadia.ee/event/tallinna-fci-levadia-vs-tartu-jk-tammeka-44942/",
    },
    {
        "sportybet_event_id": "sr:match:74374528",
        "home": "SV 07 Elversberg", "away": "Darmstadt",
        "date": "2026-10-27", "home_score": 0, "away_score": 2,
        "evidence_url": "https://sv07elversberg.de/trotz-vieler-und-guter-chancen-sve-verliert-pokal-fight-gegen-darmstadt/",
    },
    {
        "sportybet_event_id": "sr:match:74374512",
        "home": "Bochum", "away": "Mainz",
        "date": "2026-10-27", "home_score": 2, "away_score": 0,
        "evidence_url": "https://www.dfb.de/news/erster-bundesligist-raus-bochum-stuerzt-mainz",
    },
    # One-time UEFA Conference League reconciliation, matchdays 1 and 2.
    # Manually reviewed final scores on the official 2026/27 results report.
    # Exact production SportyBet IDs, both clubs and UTC dates are mandatory.
    {"sportybet_event_id": "sr:match:74173166", "home": "PFC CSKA Sofia",
     "away": "Monaco", "date": "2026-10-15",
     "home_score": 1, "away_score": 2,
     "evidence_url": "https://www.uefa.com/uefaconferenceleague/news/02a8-2174cb200f25-b94693ddff4e-1000--2026-27-conference-league-all-the-league-phase-fixtures/"},
    {"sportybet_event_id": "sr:match:74173200", "home": "St. Truidense VV",
     "away": "FC Iberia 1999", "date": "2026-10-15",
     "home_score": 2, "away_score": 0,
     "evidence_url": "https://www.uefa.com/uefaconferenceleague/news/02a8-2174cb200f25-b94693ddff4e-1000--2026-27-conference-league-all-the-league-phase-fixtures/"},
    {"sportybet_event_id": "sr:match:74173188", "home": "Copenhagen",
     "away": "Braga", "date": "2026-10-15",
     "home_score": 3, "away_score": 0,
     "evidence_url": "https://www.uefa.com/uefaconferenceleague/news/02a8-2174cb200f25-b94693ddff4e-1000--2026-27-conference-league-all-the-league-phase-fixtures/"},
    {"sportybet_event_id": "sr:match:74173224", "home": "Crvena Zvezda",
     "away": "Copenhagen", "date": "2026-10-22",
     "home_score": 2, "away_score": 2,
     "evidence_url": "https://www.uefa.com/uefaconferenceleague/news/02a8-2174cb200f25-b94693ddff4e-1000--2026-27-conference-league-all-the-league-phase-fixtures/"},
    {"sportybet_event_id": "sr:match:74173250", "home": "Ajax",
     "away": "Atalanta", "date": "2026-10-22",
     "home_score": 2, "away_score": 0,
     "evidence_url": "https://www.uefa.com/uefaconferenceleague/news/02a8-2174cb200f25-b94693ddff4e-1000--2026-27-conference-league-all-the-league-phase-fixtures/"},
    {"sportybet_event_id": "sr:match:74173266", "home": "FC Thun",
     "away": "HNK Hajduk Split", "date": "2026-10-22",
     "home_score": 0, "away_score": 1,
     "evidence_url": "https://www.uefa.com/uefaconferenceleague/news/02a8-2174cb200f25-b94693ddff4e-1000--2026-27-conference-league-all-the-league-phase-fixtures/"},
    {"sportybet_event_id": "sr:match:74173262", "home": "FC Midtjylland",
     "away": "St. Truidense VV", "date": "2026-10-22",
     "home_score": 0, "away_score": 1,
     "evidence_url": "https://www.uefa.com/uefaconferenceleague/news/02a8-2174cb200f25-b94693ddff4e-1000--2026-27-conference-league-all-the-league-phase-fixtures/"},
    # Monday 19 October 2026 — existing admin-curated fixtures.
    # Exact immutable SportyBet IDs from editorial_tier_slips in production.
    # Independent league/club match reports confirm FT regulation scores.
    # Both losing legs resolve the corresponding parent manual accumulator
    # while any other unavailable score must stay PENDING.
    {
        "sportybet_event_id": "sr:match:75243922",
        "home": "Braga", "away": "Gil Vicente Barcelos",
        "date": "2026-10-19", "home_score": 1, "away_score": 2,
        "evidence_url": "https://www.ligaportugal.pt/match/20262027/ligaportugalbetclic/2/4?tab=match_formations",
    },
    {
        "sportybet_event_id": "sr:match:72044748",
        "home": "Jong PSV Eindhoven", "away": "FC Dordrecht",
        "date": "2026-10-19", "home_score": 0, "away_score": 1,
        "evidence_url": "https://www.psv.nl/match-center/wedstrijd/jong-psv-fc-dordrecht-19-10-2026",
    },
)


def incident_finals(picks: list[dict]) -> list[dict]:
    """Return reviewed finals only for exact event ID, clubs and kickoff day."""
    from leagues.results_checker import _normalize_name

    by_id = {item["sportybet_event_id"]: item for item in _VERIFIED_FINALS}
    matched: list[dict] = []
    for pick in picks:
        event_id = str(pick.get("sportybet_event_id") or "")
        verified = by_id.get(event_id)
        if not verified:
            continue
        kickoff = pick.get("commence_time") or pick.get("kickoff") or ""
        try:
            parsed = datetime.fromisoformat(str(kickoff).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        if parsed.tzinfo is None:
            continue
        date = parsed.astimezone(timezone.utc).date().isoformat()
        if (date != verified["date"]
                or _normalize_name(pick.get("home_team") or "") != _normalize_name(verified["home"])
                or _normalize_name(pick.get("away_team") or "") != _normalize_name(verified["away"])):
            continue
        matched.append({
            **verified,
            "completed": True,
            "provider": "verified-official-fixture-report",
            "provider_event_id": event_id,
            "match_status": "STATUS_FULL_TIME",
            "score_90": {"home": verified["home_score"], "away": verified["away_score"]},
        })
    return matched
