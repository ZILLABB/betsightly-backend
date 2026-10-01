"""Pinned OpenFootball results used only as league-level history priors.

Safety contract:
- ESPN remains the primary live/recent history source.
- These rows are used only when ESPN returns a clean empty history window or
  explicitly reports a permanently unsupported league.
- They are never merged into current team-form history.
- They are never used for as-of replay, avoiding later-snapshot leakage.
- Every source is pinned to a verified repository commit.
"""

from __future__ import annotations

import re
import threading
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from leagues.openfootball_history import (
    SourceFile,
    _request_text,
    parse_openfootball_text,
)

SOURCE_NAME = "OPENFOOTBALL_PINNED_RESULTS_PRIOR"
LOOKBACK_DAYS = 730

PINNED_COMMITS = {
    "europe": "e16fa332068b639c4210d57319df459b190470dd",
    "world": "42df8203e73e922cdfa36104e3acee3aea1f2bc0",
    "champions-league": "abfaeddc2ee3d14f99ecc163c9ddb46cb4d67cef",
}

VERIFIED_SOURCES = {
    "aus.1": {
        "competition": "A-League",
        "repo": "world",
        "paths": (
            "pacific/australia/2023-24_au1.txt",
            "pacific/australia/2024-25_au1.txt",
        ),
    },
    "cze.1": {
        "competition": "Czech First League",
        "repo": "europe",
        "paths": (
            "czech-republic/2023-24_cz1.txt",
            "czech-republic/2024-25_cz1.txt",
        ),
    },
    "pol.1": {
        "competition": "Ekstraklasa",
        "repo": "europe",
        "paths": (
            "poland/2023-24_pl1.txt",
            "poland/2024-25_pl1.txt",
        ),
    },
    "rou.1": {
        "competition": "Liga I",
        "repo": "europe",
        "paths": (
            "romania/2023-24_ro1.txt",
            "romania/2024-25_ro1.txt",
        ),
    },
    "srb.1": {
        "competition": "Serbian SuperLiga",
        "repo": "europe",
        "paths": (
            "serbia/2023-24_rs1.txt",
            "serbia/2024-25_rs1.txt",
        ),
    },
    "uefa.europa.conf": {
        "competition": "UEFA Conference League",
        "repo": "champions-league",
        "paths": (
            "2024-25/conf.txt",
            "2024-25/confq.txt",
            "2025-26/confq.txt",
        ),
    },
}

_STATUS_LOCK = threading.Lock()
_LAST_STATUS: dict[str, dict] = {}


def _season_from_path(path: str) -> str:
    match = re.search(r"(\d{4}(?:-\d{2})?)", path)
    return match.group(1) if match else "unknown"


@lru_cache(maxsize=64)
def _parsed_source(
    repo: str,
    commit: str,
    path: str,
    competition: str,
) -> tuple[tuple[str, str, str, int, int], ...]:
    source = SourceFile(
        repo=repo,
        path=path,
        league_id=0,
        competition=competition,
        season=_season_from_path(path),
        commit_sha=commit,
    )
    text = _request_text(source.raw_url)
    rows, _ = parse_openfootball_text(text, source)
    return tuple(
        (
            row.date,
            row.home_team,
            row.away_team,
            int(row.home_score),
            int(row.away_score),
        )
        for row in rows
    )


def _set_status(slug: str, value: dict) -> None:
    with _STATUS_LOCK:
        _LAST_STATUS[slug] = dict(value)


def status() -> dict[str, dict]:
    with _STATUS_LOCK:
        return {
            slug: dict(value)
            for slug, value in _LAST_STATUS.items()
        }


def supports(slug: str) -> bool:
    return str(slug or "") in VERIFIED_SOURCES


def finished_scores(
    slug: str,
    *,
    as_of: datetime | None = None,
    lookback_days: int = LOOKBACK_DAYS,
) -> list[tuple[int, int]]:
    """Return pinned result scores for a verified competition prior.

    This intentionally refuses as-of replay. The source snapshot was observed
    later than historical replay cutoffs, so using it there would weaken the
    project's no-leakage guarantee.
    """

    slug = str(slug or "")

    if as_of is not None:
        _set_status(slug, {
            "status": "DISABLED_FOR_AS_OF_REPLAY",
            "source": SOURCE_NAME,
            "matches": 0,
        })
        return []

    config = VERIFIED_SOURCES.get(slug)
    if not config:
        return []

    cutoff = datetime.now(timezone.utc).date() - timedelta(days=1)
    earliest = cutoff - timedelta(days=max(1, int(lookback_days)))

    repo = str(config["repo"])
    commit = PINNED_COMMITS[repo]
    competition = str(config["competition"])

    rows: dict[tuple[str, str, str], tuple[int, int]] = {}
    errors = []

    for path in config["paths"]:
        try:
            parsed = _parsed_source(
                repo,
                commit,
                str(path),
                competition,
            )
        except Exception as exc:
            errors.append(f"{path}: {type(exc).__name__}")
            continue

        for date_text, home, away, home_score, away_score in parsed:
            try:
                day = datetime.strptime(date_text, "%Y-%m-%d").date()
            except (TypeError, ValueError):
                continue
            if not (earliest <= day <= cutoff):
                continue
            rows[(date_text, home, away)] = (home_score, away_score)

    ordered_keys = sorted(rows)
    scores = [rows[key] for key in ordered_keys]

    _set_status(slug, {
        "status": "READY" if scores else ("ERROR" if errors else "EMPTY"),
        "source": SOURCE_NAME,
        "matches": len(scores),
        "min_date": ordered_keys[0][0] if ordered_keys else None,
        "max_date": ordered_keys[-1][0] if ordered_keys else None,
        "repository": f"openfootball/{repo}",
        "commit": commit,
        "paths": list(config["paths"]),
        "lookback_days": int(lookback_days),
        "errors": errors,
        "current_team_form": False,
        "as_of_replay_allowed": False,
    })
    return scores
