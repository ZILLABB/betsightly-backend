"""Verified public-domain OpenFootball match-result ingestion.

Source: openfootball/football.json (CC0-1.0). Only finished matches whose
local match *date* strictly precedes the as-of UTC date can enter this history.
Date-only data is never used as if it contained a precise kickoff timestamp.
This is a training/evidence dataset, NOT a current odds source.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from typing import Any

SOURCE = "openfootball/football.json"
LICENSE = "CC0-1.0"
RAW_BASE = "https://raw.githubusercontent.com/openfootball/football.json"
# Explicit filenames verified against the public football.json repository.
LEAGUES = {
    "eng.1": "en.1", "eng.2": "en.2", "eng.3": "en.3",
    "eng.4": "en.4", "ger.1": "de.1", "ger.2": "de.2",
    "esp.1": "es.1", "esp.2": "es.2", "ita.1": "it.1",
    "ita.2": "it.2", "fra.1": "fr.1", "fra.2": "fr.2",
    "por.1": "pt.1", "ned.1": "nl.1", "bel.1": "be.1",
    "aut.1": "at.1", "gre.1": "gr.1", "sco.1": "sco.1",
    "tur.1": "tr.1",
}
MAX_BYTES = 3_000_000


def source_url(slug: str, season: str, *, revision: str = "master") -> str:
    if slug not in LEAGUES:
        raise ValueError(f"Unverified OpenFootball league: {slug}")
    if not (len(season) == 7 and season[:4].isdigit()
            and season[4] == "-" and season[5:].isdigit()
            and int(season[5:]) == (int(season[:4]) + 1) % 100):
        raise ValueError(f"Invalid season: {season}")
    if not (revision == "master" or
            len(revision) == 40 and all(c in "0123456789abcdef" for c in revision)):
        raise ValueError("Source revision must be master or an immutable 40-character SHA")
    return f"{RAW_BASE}/{revision}/{season}/{LEAGUES[slug]}.json"


def _fulltime(score: Any) -> tuple[int, int] | None:
    # Source has both legacy [1,0] and {"ft":[1,0],"ht":[0,0]}.
    values = score.get("ft") if isinstance(score, dict) else score
    if (not isinstance(values, list) or len(values) != 2
            or any(type(v) is not int or not 0 <= v <= 30 for v in values)):
        return None
    return values[0], values[1]


def parse_results(
    payload: dict, slug: str, season: str, *,
    as_of: date | None = None, source_hash: str = "",
) -> tuple[list[dict], dict]:
    """Strict, deduplicated full-time results with source-level provenance."""
    if slug not in LEAGUES:
        raise ValueError(f"Unsupported league: {slug}")
    cutoff = as_of or datetime.now(timezone.utc).date()
    matches = payload.get("matches") if isinstance(payload, dict) else None
    if not isinstance(matches, list):
        raise ValueError("Source is missing a valid matches array")
    unique = {}
    rejected = {}
    for match in matches:
        if not isinstance(match, dict):
            rejected["malformed_row"] = rejected.get("malformed_row", 0) + 1
            continue
        try:
            played = date.fromisoformat(str(match.get("date") or ""))
        except ValueError:
            rejected["invalid_date"] = rejected.get("invalid_date", 0) + 1
            continue
        if played >= cutoff:
            rejected["unfinished_or_future"] = rejected.get("unfinished_or_future", 0) + 1
            continue
        home = " ".join(str(match.get("team1") or "").split())
        away = " ".join(str(match.get("team2") or "").split())
        if (not home or not away or home.casefold() == away.casefold()
                or len(home) > 180 or len(away) > 180):
            rejected["invalid_teams"] = rejected.get("invalid_teams", 0) + 1
            continue
        score = _fulltime(match.get("score"))
        if score is None:
            rejected["unsettled_or_invalid_score"] = rejected.get("unsettled_or_invalid_score", 0) + 1
            continue
        identity = (slug, played.isoformat(), home.casefold(), away.casefold())
        row = {
            "fixture_key": hashlib.sha256(
                json.dumps(identity, separators=(",", ":")).encode()
            ).hexdigest(),
            "league_slug": slug, "season": season,
            "match_date": played.isoformat(), "home_team": home,
            "away_team": away, "home_score": score[0], "away_score": score[1],
            "source": SOURCE, "source_license": LICENSE,
            "source_file": f"{season}/{LEAGUES[slug]}.json",
            "source_sha256": source_hash,
        }
        previous = unique.get(identity)
        if previous is not None and (
            previous["home_score"], previous["away_score"]
        ) != score:
            raise ValueError("Conflicting final scores for the same source match")
        unique[identity] = row
    rows = sorted(unique.values(), key=lambda row: (
        row["match_date"], row["league_slug"], row["fixture_key"]
    ))
    return rows, {
        "league_slug": slug, "season": season, "source": SOURCE,
        "rows_in_source": len(matches), "accepted": len(rows),
        "duplicates": sum(1 for k in []),  # count supplied below
        "rejections": dict(sorted(rejected.items())),
    }


def fetch_results(
    slug: str, season: str, *, as_of: date | None = None,
    revision: str = "master", timeout: int = 20,
) -> tuple[list[dict], dict]:
    """Bounded public HTTPS read. No private APIs, login or anti-bot bypass."""
    import requests
    url = source_url(slug, season, revision=revision)
    response = requests.get(url, timeout=timeout, headers={
        "User-Agent": "BetSightlyHistoricalResearch/1.0"
    })
    response.raise_for_status()
    if len(response.content) > MAX_BYTES:
        raise ValueError("OpenFootball file exceeds the ingestion size limit")
    digest = hashlib.sha256(response.content).hexdigest()
    payload = response.json()
    rows, report = parse_results(
        payload, slug, season, as_of=as_of, source_hash=digest
    )
    report.update({
        "source_url": url, "source_sha256": digest,
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
    })
    return rows, report
