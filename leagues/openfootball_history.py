\
"""OpenFootball results-only historical ingestion for BetSightly.

This module deliberately does NOT provide bookmaker odds. It builds an isolated
football-history dataset for form/Elo/replay work and keeps source provenance on
every normalized row.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import unicodedata
import urllib.request
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

PROVIDER = "OpenFootball"
LICENSE = "CC0-1.0 / public domain"
GITHUB_API = "https://api.github.com"
RAW_GITHUB = "https://raw.githubusercontent.com/openfootball"

MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}

DATE_RE = re.compile(
    r"^\s*(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+"
    r"(?P<month>[A-Z][a-z]{2})\s+(?P<day>\d{1,2})"
    r"(?:\s+(?P<year>\d{4}))?\s*$"
)
TIME_RE = re.compile(r"^\s*\d{1,2}:\d{2}(?:\s+UTC[+-]\d{1,2})?\s+")
COUNTRY_SUFFIX_RE = re.compile(r"\s+\([A-Z]{3}\)\s*$")
SIMPLE_SCORE_RE = re.compile(
    r"^(?P<home>.+?)\s+v\s+(?P<away>.+?)\s+"
    r"(?P<h>\d{1,2})-(?P<a>\d{1,2})"
    r"(?:\s+\((?P<hth>\d{1,2})-(?P<hta>\d{1,2})\))?"
    r"(?:\s+@.*)?\s*$"
)
WORLD_CUP_SCORE_RE = re.compile(
    r"^(?P<home>.+?)\s+"
    r"(?P<h>\d{1,2})-(?P<a>\d{1,2})"
    r"(?:\s+\((?P<hth>\d{1,2})-(?P<hta>\d{1,2})\))?"
    r"\s+(?P<away>.+?)"
    r"(?:\s+@.*)?\s*$"
)

FIELDNAMES = [
    "date",
    "season",
    "league_id",
    "competition",
    "home_team",
    "away_team",
    "home_score",
    "away_score",
    "ht_home_score",
    "ht_away_score",
    "provider",
    "source_repo",
    "source_commit",
    "source_file",
    "source_url",
    "source_file_sha256",
    "source_row_id",
    "source_class",
    "bookmaker_odds_history",
    "odds_source",
    "odds_snapshot_type",
    "odds_captured_at",
]

COMPETITION_PATTERNS = (
    (
        "worldcup",
        re.compile(r"^(?P<season>\d{4})--[^/]+/cup(?:_finals)?\.txt$"),
        1,
        "FIFA World Cup",
    ),
    (
        "champions-league",
        re.compile(r"^(?P<season>\d{4}-\d{2})/clq?\.txt$"),
        2,
        "UEFA Champions League",
    ),
    (
        "champions-league",
        re.compile(r"^(?P<season>\d{4}-\d{2})/elq?\.txt$"),
        3,
        "UEFA Europa League",
    ),
    (
        "champions-league",
        re.compile(r"^(?P<season>\d{4}-\d{2})/confq?\.txt$"),
        848,
        "UEFA Conference League",
    ),
    (
        "south-america",
        re.compile(r"^copa-libertadores/(?P<season>\d{4})_copal\.txt$"),
        13,
        "Copa Libertadores",
    ),
    (
        "south-america",
        re.compile(r"^copa-libertadores/(?P<season>\d{4})_copas\.txt$"),
        11,
        "Copa Sudamericana",
    ),
)


@dataclass(frozen=True)
class SourceFile:
    repo: str
    path: str
    league_id: int
    competition: str
    season: str
    commit_sha: str

    @property
    def raw_url(self) -> str:
        return f"{RAW_GITHUB}/{self.repo}/{self.commit_sha}/{self.path}"


@dataclass(frozen=True)
class ParsedMatch:
    date: str
    season: str
    league_id: int
    competition: str
    home_team: str
    away_team: str
    home_score: int
    away_score: int
    ht_home_score: int | None
    ht_away_score: int | None
    provider: str
    source_repo: str
    source_commit: str
    source_file: str
    source_url: str
    source_file_sha256: str
    source_row_id: str
    source_class: str = "RESULTS_ONLY"
    bookmaker_odds_history: bool = False
    odds_source: str = ""
    odds_snapshot_type: str = ""
    odds_captured_at: str = ""

    def as_row(self) -> dict:
        value = asdict(self)
        value["bookmaker_odds_history"] = "false"
        return value


def _request_json(url: str, timeout: int = 30) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "BetSightly-football-history-audit",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _request_text(url: str, timeout: int = 30) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "BetSightly-football-history-audit"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8-sig")


def normalize_team(value: str) -> str:
    value = COUNTRY_SUFFIX_RE.sub("", value.strip())
    value = unicodedata.normalize("NFKC", value)
    return re.sub(r"\s+", " ", value).strip()


def team_key(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.casefold()
    return re.sub(r"[^a-z0-9]+", "", value)


def source_start_year(season: str) -> int:
    return int(season[:4])


def source_year_bounds(season: str) -> tuple[int, int]:
    start = source_start_year(season)
    if "-" not in season:
        return start, start
    suffix = int(season.split("-", 1)[1])
    end = (start // 100) * 100 + suffix
    if end < start:
        end += 100
    return start, end


def classify_source_path(repo: str, path: str, commit_sha: str) -> SourceFile | None:
    for expected_repo, pattern, league_id, competition in COMPETITION_PATTERNS:
        if repo != expected_repo:
            continue
        match = pattern.match(path)
        if not match:
            continue
        return SourceFile(
            repo=repo,
            path=path,
            league_id=league_id,
            competition=competition,
            season=match.group("season"),
            commit_sha=commit_sha,
        )
    return None


def resolve_repo_snapshot(repo: str) -> tuple[str, str]:
    commit = _request_json(f"{GITHUB_API}/repos/openfootball/{repo}/commits/master")
    commit_sha = commit["sha"]
    tree_sha = commit["commit"]["tree"]["sha"]
    return commit_sha, tree_sha


def _discover_sources_live(
    *,
    min_year: int = 2012,
    max_year: int | None = None,
) -> tuple[list[SourceFile], dict[str, str]]:
    max_year = max_year or date.today().year
    sources: list[SourceFile] = []
    snapshots: dict[str, str] = {}

    for repo in ("worldcup", "champions-league", "south-america"):
        commit_sha, tree_sha = resolve_repo_snapshot(repo)
        snapshots[repo] = commit_sha
        tree = _request_json(
            f"{GITHUB_API}/repos/openfootball/{repo}/git/trees/{tree_sha}?recursive=1"
        )
        if tree.get("truncated"):
            raise RuntimeError(f"GitHub tree was truncated for openfootball/{repo}")

        for item in tree.get("tree", []):
            if item.get("type") != "blob":
                continue
            source = classify_source_path(repo, item["path"], commit_sha)
            if source is None:
                continue
            start_year = source_start_year(source.season)
            if min_year <= start_year <= max_year:
                sources.append(source)

    sources.sort(key=lambda item: (item.league_id, item.season, item.path))
    return sources, snapshots




def _discover_sources_from_cached_manifest(
    *,
    min_year: int = 2012,
    max_year: int | None = None,
) -> tuple[list[SourceFile], dict[str, str]] | None:
    """Reuse the last verified pinned OpenFootball snapshot.

    This avoids depending on the GitHub API for every deterministic rebuild.
    Raw source files are still fetched from their exact pinned commit SHA.
    """
    manifest_path = Path("data") / "football_history" / "manifest.json"
    if not manifest_path.exists():
        return None

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    snapshots = dict(manifest.get("source_snapshots") or {})
    previous_files = manifest.get("source_files") or []
    if not snapshots or not previous_files:
        return None

    max_year = max_year or date.today().year
    sources: list[SourceFile] = []
    seen: set[tuple[str, str, str]] = set()

    def add_source(source: SourceFile) -> None:
        start_year = source_start_year(source.season)
        key = (source.repo, source.path, source.commit_sha)
        if min_year <= start_year <= max_year and key not in seen:
            seen.add(key)
            sources.append(source)

    for item in previous_files:
        repo = str(item.get("repo") or "")
        path = str(item.get("path") or "")
        season = str(item.get("season") or "")
        commit_sha = str(
            item.get("commit_sha")
            or snapshots.get(repo)
            or ""
        )

        if not repo or not path or not season or not commit_sha:
            continue

        classified = classify_source_path(repo, path, commit_sha)
        if classified is not None:
            add_source(classified)

        # OpenFootball stores World Cup knockout rounds separately.
        # These three finals files were verified explicitly.
        if (
            repo == "worldcup"
            and path.endswith("/cup.txt")
            and season in {"2014", "2018", "2022"}
        ):
            finals_path = path[:-len("cup.txt")] + "cup_finals.txt"
            add_source(
                SourceFile(
                    repo="worldcup",
                    path=finals_path,
                    league_id=1,
                    competition="FIFA World Cup",
                    season=season,
                    commit_sha=commit_sha,
                )
            )

    sources.sort(
        key=lambda item: (
            item.league_id,
            item.season,
            item.path,
        )
    )
    return sources, snapshots


def discover_sources(
    *,
    min_year: int = 2012,
    max_year: int | None = None,
) -> tuple[list[SourceFile], dict[str, str]]:
    cached = _discover_sources_from_cached_manifest(
        min_year=min_year,
        max_year=max_year,
    )
    if cached is not None:
        return cached

    return _discover_sources_live(
        min_year=min_year,
        max_year=max_year,
    )

def _parse_date_line(
    line: str,
    *,
    current_year: int,
    previous_month: int | None,
    season_start_year: int,
    season_end_year: int,
) -> tuple[str | None, int, int | None]:
    match = DATE_RE.match(line)
    if not match:
        return None, current_year, previous_month

    month = MONTHS[match.group("month")]
    explicit_year = match.group("year")
    if explicit_year:
        current_year = int(explicit_year)
    elif (
        season_end_year > season_start_year
        and previous_month is not None
        and previous_month >= 7
        and month <= 6
    ):
        current_year = min(current_year + 1, season_end_year)
    elif season_end_year == season_start_year:
        current_year = season_start_year

    current_year = min(max(current_year, season_start_year), season_end_year)
    parsed = date(current_year, month, int(match.group("day")))
    return parsed.isoformat(), current_year, month


def _has_ambiguous_knockout_score(body: str) -> bool:
    lowered = body.casefold()
    return "pen." in lowered or " aet" in lowered or "a.e.t" in lowered


def _split_simple_match(
    line: str,
    *,
    league_id: int | None = None,
) -> tuple[str, str, int, int, int | None, int | None] | None:
    body = TIME_RE.sub("", line.strip())

    if _has_ambiguous_knockout_score(body):
        return None

    match = SIMPLE_SCORE_RE.match(body)
    if match is None and league_id == 1:
        match = WORLD_CUP_SCORE_RE.match(body)
    if not match:
        return None

    home = normalize_team(match.group("home"))
    away = normalize_team(match.group("away"))
    if not home or not away:
        return None

    return (
        home,
        away,
        int(match.group("h")),
        int(match.group("a")),
        int(match.group("hth")) if match.group("hth") is not None else None,
        int(match.group("hta")) if match.group("hta") is not None else None,
    )


def parse_openfootball_text(
    text: str,
    source: SourceFile,
) -> tuple[list[ParsedMatch], dict[str, int]]:
    season_start_year, season_end_year = source_year_bounds(source.season)
    current_year = season_start_year
    current_date: str | None = None
    previous_month: int | None = None
    file_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()

    matches: list[ParsedMatch] = []
    stats = {
        "lines": 0,
        "date_lines": 0,
        "matches": 0,
        "excluded_knockout_score_semantics": 0,
        "score_like_without_date": 0,
    }

    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        stats["lines"] += 1

        maybe_date, current_year, new_month = _parse_date_line(
            raw_line,
            current_year=current_year,
            previous_month=previous_month,
            season_start_year=season_start_year,
            season_end_year=season_end_year,
        )
        if maybe_date is not None:
            current_date = maybe_date
            previous_month = new_month
            stats["date_lines"] += 1
            continue

        body = raw_line.strip()
        if not body:
            continue

        if _has_ambiguous_knockout_score(body):
            stats["excluded_knockout_score_semantics"] += 1
            continue

        parsed = _split_simple_match(raw_line, league_id=source.league_id)
        if parsed is None:
            continue

        if current_date is None:
            stats["score_like_without_date"] += 1
            continue

        home, away, hs, aw, hth, hta = parsed
        source_row_id = hashlib.sha256(
            (
                f"{source.repo}|{source.commit_sha}|{source.path}|{line_no}|"
                f"{current_date}|{home}|{away}|{hs}-{aw}"
            ).encode("utf-8")
        ).hexdigest()[:24]

        matches.append(
            ParsedMatch(
                date=current_date,
                season=source.season,
                league_id=source.league_id,
                competition=source.competition,
                home_team=home,
                away_team=away,
                home_score=hs,
                away_score=aw,
                ht_home_score=hth,
                ht_away_score=hta,
                provider=PROVIDER,
                source_repo=f"openfootball/{source.repo}",
                source_commit=source.commit_sha,
                source_file=source.path,
                source_url=source.raw_url,
                source_file_sha256=file_sha,
                source_row_id=source_row_id,
            )
        )
        stats["matches"] += 1

    return matches, stats


def fixture_key(match: ParsedMatch) -> tuple:
    return (
        match.league_id,
        match.date,
        team_key(match.home_team),
        team_key(match.away_team),
    )


def deduplicate_matches(
    matches: Iterable[ParsedMatch],
) -> tuple[list[ParsedMatch], dict[str, int]]:
    by_key: dict[tuple, ParsedMatch] = {}
    exact_duplicates = 0

    for match in matches:
        key = fixture_key(match)
        prior = by_key.get(key)
        if prior is None:
            by_key[key] = match
            continue

        prior_score = (prior.home_score, prior.away_score)
        new_score = (match.home_score, match.away_score)
        if prior_score != new_score:
            raise ValueError(
                "Conflicting historical fixture: "
                f"{key}: {prior_score} vs {new_score} "
                f"({prior.source_file} vs {match.source_file})"
            )
        exact_duplicates += 1

    rows = sorted(
        by_key.values(),
        key=lambda item: (item.date, item.league_id, item.home_team, item.away_team),
    )
    return rows, {
        "input_matches": len(by_key) + exact_duplicates,
        "unique_matches": len(rows),
        "exact_duplicates_removed": exact_duplicates,
        "conflicting_duplicates": 0,
    }


def historical_cutoff(max_year: int | None = None, *, today: date | None = None) -> date:
    today = today or date.today()
    requested_max = max_year or today.year
    return min(date(requested_max, 12, 31), today - timedelta(days=1))


def build_dataset(
    *,
    output_csv: Path,
    manifest_json: Path,
    min_year: int = 2012,
    max_year: int | None = None,
) -> dict:
    sources, snapshots = discover_sources(min_year=min_year, max_year=max_year)
    all_matches: list[ParsedMatch] = []
    source_stats: list[dict] = []

    for source in sources:
        text = _request_text(source.raw_url)
        parsed, stats = parse_openfootball_text(text, source)
        all_matches.extend(parsed)
        source_stats.append(
            {
                "repo": source.repo,
                "path": source.path,
                "league_id": source.league_id,
                "competition": source.competition,
                "season": source.season,
                "commit_sha": source.commit_sha,
                **stats,
            }
        )

    cutoff = historical_cutoff(max_year)
    eligible_matches = [
        row for row in all_matches
        if date.fromisoformat(row.date) <= cutoff
    ]
    future_rows_excluded = len(all_matches) - len(eligible_matches)

    rows, dedupe = deduplicate_matches(eligible_matches)
    dedupe["future_rows_excluded"] = future_rows_excluded
    dedupe["historical_cutoff_date"] = cutoff.isoformat()

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.as_row())

    by_league: dict[str, dict] = {}
    for row in rows:
        key = str(row.league_id)
        item = by_league.setdefault(
            key,
            {
                "league_id": row.league_id,
                "competition": row.competition,
                "rows": 0,
                "min_date": row.date,
                "max_date": row.date,
            },
        )
        item["rows"] += 1
        item["min_date"] = min(item["min_date"], row.date)
        item["max_date"] = max(item["max_date"], row.date)

    output_sha = hashlib.sha256(output_csv.read_bytes()).hexdigest()
    manifest = {
        "schema": 1,
        "dataset": "football_history",
        "source_class": "RESULTS_ONLY",
        "provider": PROVIDER,
        "license": LICENSE,
        "min_year": min_year,
        "max_year": max_year or date.today().year,
        "historical_cutoff_date": cutoff.isoformat(),
        "future_rows_excluded": future_rows_excluded,
        "source_snapshots": snapshots,
        "source_file_count": len(sources),
        "source_files": source_stats,
        "deduplication": dedupe,
        "coverage": sorted(by_league.values(), key=lambda item: item["league_id"]),
        "output_csv": str(output_csv),
        "output_sha256": output_sha,
        "bookmaker_odds_history": False,
        "market_training_eligible": False,
        "notes": [
            "This dataset is isolated from the deployed market-feature training corpus.",
            "Penalty/extra-time rows with ambiguous 90-minute score semantics are excluded fail-closed.",
            "No bookmaker odds are fabricated or inferred.",
        ],
    }
    manifest_json.parent.mkdir(parents=True, exist_ok=True)
    manifest_json.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest
