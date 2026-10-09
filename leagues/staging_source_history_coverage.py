"""Staging-only evidence coverage from verified-date public match results.

Reports which bookmaker-native fixtures acquire *potential* prior match
history. This never calls predictor.predict and does not make a ticket eligible
for production. League and team identities must both match exactly after the
existing normalization policy, and only earlier played games are counted.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

WAT = timezone(timedelta(hours=1))
MIN_COMPETITION_MATCHES = 10
MIN_TEAM_MATCHES = 3
MAX_TEAM_LATEST_AGE_DAYS = 180
MAX_HISTORY_DAYS = 365


def compare_coverage(
    board: dict, historical_rows: list[dict], target_day: str,
    *, existing_event_ids: frozenset[str] = frozenset(),
) -> dict:
    from leagues import sportybet
    today = date.fromisoformat(target_day)
    since = today - timedelta(days=MAX_HISTORY_DAYS)
    league_games = defaultdict(set)
    team_games = defaultdict(lambda: defaultdict(set))
    team_recent = {}
    for row in historical_rows:
        slug = str(row.get("league_slug") or "")
        try:
            played = date.fromisoformat(str(row.get("match_date") or ""))
        except ValueError:
            continue
        if not since <= played < today:
            continue
        home = sportybet._norm(row.get("home_team") or "")
        away = sportybet._norm(row.get("away_team") or "")
        key = str(row.get("fixture_key") or "")
        if not slug or not key or not home or not away or home == away:
            continue
        league_games[slug].add(key)
        for team in (home, away):
            team_games[slug][team].add(key)
            identity = (slug, team)
            team_recent[identity] = max(
                team_recent.get(identity, played), played,
            )

    states = Counter()
    per_league = defaultdict(Counter)
    opportunities = []
    seen = set()
    for _, entry in sportybet._board_entries(board):
        event_id = str(entry.get("event_id") or "")
        if not event_id or event_id in seen:
            continue
        seen.add(event_id)
        try:
            kickoff = datetime.fromtimestamp(
                int(entry["kickoff_ms"]) / 1000, tz=timezone.utc,
            ).astimezone(WAT).date()
        except (ValueError, TypeError, KeyError, OverflowError, OSError):
            continue
        if kickoff != today:
            continue
        if event_id in existing_event_ids:
            states["ALREADY_MODELLED_FROM_ESPN"] += 1
            continue
        mapping = sportybet.registry_competition_match(
            str(entry.get("competition") or ""),
            tournament_id=entry.get("sportybet_tournament_id"),
            category_id=entry.get("sportybet_category_id"),
        )
        slug = mapping.get("league_slug")
        if mapping.get("status") != "MAPPED_EXACT" or not slug:
            states["UNMAPPED_COMPETITION"] += 1
            continue
        if entry.get("home_squad") or entry.get("away_squad"):
            states["UNSUPPORTED_SQUAD"] += 1
            continue
        home = sportybet._norm(entry.get("home_team") or "")
        away = sportybet._norm(entry.get("away_team") or "")
        if not home or not away or home == away:
            state = "AMBIGUOUS_TEAM_IDENTITY"
        elif len(league_games[slug]) < MIN_COMPETITION_MATCHES:
            state = "MISSING_COMPETITION_HISTORY"
        elif (len(team_games[slug].get(home, ())) < MIN_TEAM_MATCHES
              or len(team_games[slug].get(away, ())) < MIN_TEAM_MATCHES):
            state = "MISSING_TEAM_HISTORY"
        elif (today - team_recent[(slug, home)]).days > MAX_TEAM_LATEST_AGE_DAYS or (
            today - team_recent[(slug, away)]
        ).days > MAX_TEAM_LATEST_AGE_DAYS:
            state = "STALE_TEAM_HISTORY"
        elif not entry.get("prices"):
            state = "NO_BOOKMAKER_PRICES"
        else:
            state = "POTENTIAL_SHADOW_HISTORY_READY"
        states[state] += 1
        per_league[slug][state] += 1
        if state == "POTENTIAL_SHADOW_HISTORY_READY":
            opportunities.append({
                "event_id": event_id,
                "league_slug": slug,
                "home_history": len(team_games[slug][home]),
                "away_history": len(team_games[slug][away]),
                "competition_history": len(league_games[slug]),
            })
    return {
        "target_wat_date": target_day,
        "state_counts": dict(sorted(states.items())),
        "per_league": {
            league: dict(sorted(counts.items()))
            for league, counts in sorted(per_league.items())
        },
        "shadow_ready_examples": opportunities[:30],
        "potential_shadow_ready_count": states["POTENTIAL_SHADOW_HISTORY_READY"],
        "maximum_history_days": MAX_HISTORY_DAYS,
        "publishing_changed": False,
        "prediction_pool_changed": False,
        "champion_model_unchanged": True,
        "note": (
            "Potential history readiness is not model calibration, verified "
            "team identity across providers, a proven value edge or a "
            "bookable official slip. Stage evidence for independent checks."
        ),
    }
