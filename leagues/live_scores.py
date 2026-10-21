"""
Live scores for fixtures on today's card.

ESPN's scoreboard already carries the score, the state and the clock for every
match it lists, and the card is built from that same feed — so this needs no
new data source and no new key, just a second read of what we already use.

Keyed by the card's own `match_id`, which is an md5 of home + away +
commence_time. Rebuilding the id the same way means a score lands on the right
pick without any name matching, which is where this sort of thing usually goes
wrong.

Deliberately separate from the card. The card is locked at 08:00 and must not
change; a score is live and changes every few minutes. Merging them would
force a choice between a stale score and a card that rewrites itself, so they
are fetched apart and joined in the client.
"""

import hashlib
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import requests

logger = logging.getLogger(__name__)

SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard"
TIMEOUT = 12

# ESPN state -> what a reader needs to know.
STATE_LABEL = {"pre": "not started", "in": "live", "post": "finished"}


def _normalise_commence(raw: str) -> str:
    """Match espn_source's timestamp normalisation exactly.

    ESPN returns kick-offs without seconds ("2026-07-31T23:30Z") and
    espn_source pads them to "...:30:00Z" before hashing. Reconstructing the id
    from the raw value produces a different md5 for every fixture, which is
    what made the first version of this match nothing at all.
    """
    if raw.endswith("Z") and len(raw) == 17:
        return raw[:-1] + ":00Z"
    return raw


def _match_id(home: str, away: str, commence: str) -> str:
    return hashlib.md5(
        f"{home}{away}{_normalise_commence(commence)}".encode()
    ).hexdigest()


def _fetch_league(slug: str, date_str: str) -> list[dict]:
    try:
        resp = requests.get(SCOREBOARD.format(slug=slug),
                            params={"dates": date_str}, timeout=TIMEOUT)
        if resp.status_code != 200:
            return []
        return resp.json().get("events", []) or []
    except Exception:
        return []


def _parse(event: dict) -> dict | None:
    comp = (event.get("competitions") or [{}])[0]
    teams = comp.get("competitors", []) or []
    home = next((t for t in teams if t.get("homeAway") == "home"), None)
    away = next((t for t in teams if t.get("homeAway") == "away"), None)
    if not home or not away:
        return None

    status = comp.get("status", {}) or {}
    stype = status.get("type", {}) or {}
    state = stype.get("state") or "pre"

    commence = event.get("date") or comp.get("date") or ""
    home_name = (home.get("team") or {}).get("displayName") or ""
    away_name = (away.get("team") or {}).get("displayName") or ""

    def score(side):
        try:
            return int(side.get("score"))
        except (TypeError, ValueError):
            return None

    return {
        "match_id": _match_id(home_name, away_name, commence),
        "kickoff_utc": _normalise_commence(commence),
        "source": "espn",
        "home_team": home_name,
        "away_team": away_name,
        "home_score": score(home),
        "away_score": score(away),
        "state": state,
        "state_label": STATE_LABEL.get(state, state),
        "detail": stype.get("shortDetail") or stype.get("description"),
        "clock": status.get("displayClock"),
        "period": status.get("period"),
        "finished": state == "post",
        "live": state == "in",
    }


def scores_for(slugs: list[str], date_str: str | None = None) -> dict:
    """Scores keyed by match_id for the given league slugs."""
    date_str = date_str or datetime.now(timezone.utc).strftime("%Y%m%d")
    out: dict[str, dict] = {}
    if not slugs:
        return out

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(_fetch_league, s, date_str): s for s in set(slugs)}
        for fut in as_completed(futures):
            try:
                events = fut.result()
            except Exception:
                continue
            for ev in events:
                parsed = _parse(ev)
                if parsed:
                    out[parsed["match_id"]] = parsed
    return out


def align_espn_scores_to_card(
    scoreboard: dict, games: list[dict],
    *, kickoff_tolerance_seconds: int = 20 * 60,
) -> tuple[dict, int]:
    """Conservatively map ESPN's score identity to an immutable published ID.

    A model/curated pick can carry a different fixture ID when provider name
    or kick-off formatting changed. An exact match is always preferred. For
    missing IDs require BOTH normalized team names and a UTC kick-off within
    20 minutes. Ambiguous scores or competing published games never match.
    This only adds DISPLAY scores. It is not used for official settlement.
    """
    from leagues.results_checker import _normalize_name

    def kickoff(raw):
        try:
            parsed = datetime.fromisoformat(str(raw or "").replace("Z", "+00:00"))
            return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
        except (ValueError, TypeError, OverflowError):
            return None

    unique_games = {}
    for g in games:
        if isinstance(g, dict) and g.get("match_id"):
            unique_games.setdefault(str(g["match_id"]), g)
    result = dict(scoreboard)
    potential: dict[str, list[str]] = {}
    for mid, game in unique_games.items():
        if mid in result:
            continue
        gh = _normalize_name(game.get("home_team", ""))
        ga = _normalize_name(game.get("away_team", ""))
        gt = kickoff(game.get("kickoff") or game.get("commence_time") or game.get("date"))
        if not (gh and ga and gt):
            continue
        candidates = []
        for score_id, observation in scoreboard.items():
            if not isinstance(observation, dict):
                continue
            if (_normalize_name(observation.get("home_team", "")) != gh
                    or _normalize_name(observation.get("away_team", "")) != ga):
                continue
            ft = kickoff(observation.get("kickoff_utc"))
            if ft is None:
                continue
            if abs((ft - gt).total_seconds()) <= kickoff_tolerance_seconds:
                candidates.append(score_id)
        if len(candidates) == 1:
            potential[mid] = candidates

    # One provider observation cannot be arbitrarily assigned to multiple
    # published fixture IDs. This catches repeated youth/rematch duplicates.
    claims: dict[str, int] = {}
    for candidate in potential.values():
        claims[candidate[0]] = claims.get(candidate[0], 0) + 1
    matched = 0
    for mid, ids in potential.items():
        source_id = ids[0]
        if claims[source_id] != 1:
            continue
        result[mid] = dict(scoreboard[source_id], match_id=mid,
                           identity_match="teams_and_kickoff",
                           provisional=True)
        matched += 1
    return result, matched


def overlay_sportybet_live(verified_scores: dict, games: list[dict],
                         observations: list[dict]) -> tuple[dict, int]:
    """Fill ESPN coverage gaps with *provisional in-play* SportyBet scores.

    The official settlement map is never passed here. Do not replace ESPN
    finished or in-progress scores and never treat SportyBet as a final result.
    Event ID, both teams and the UTC kickoff date must all match.
    """
    from leagues.results_checker import _normalize_name

    merged = dict(verified_scores)
    by_event: dict[str, list[dict]] = {}
    for ev in observations:
        event_id = ev.get("event_id")
        if isinstance(event_id, str):
            by_event.setdefault(event_id, []).append(ev)

    accepted = 0
    for game in games:
        mid = game.get("match_id")
        eid = str(game.get("sportybet_event_id") or
                  (game.get("sportybet_availability") or {}).get("event_id") or "")
        if not mid or not eid or len(by_event.get(eid, [])) != 1:
            continue
        existing = merged.get(mid)
        if existing and (existing.get("finished") or existing.get("live")):
            continue

        item = by_event[eid][0]
        if not item.get("live") or item.get("finished") or not item.get("provisional"):
            continue
        if (_normalize_name(item.get("home_team", "")) != _normalize_name(game.get("home_team", ""))
                or _normalize_name(item.get("away_team", "")) != _normalize_name(game.get("away_team", ""))):
            continue
        kickoff = game.get("kickoff") or game.get("commence_time") or game.get("date") or ""
        try:
            parsed = datetime.fromisoformat(str(kickoff).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                continue
            match_day = parsed.astimezone(timezone.utc).date().isoformat()
        except ValueError:
            continue
        if item.get("date") != match_day:
            continue
        # The snapshot is display-only. No official wins/losses/calibration.
        merged[mid] = {
            "match_id": mid,
            "home_team": game.get("home_team", ""),
            "away_team": game.get("away_team", ""),
            "home_score": item["home_score"],
            "away_score": item["away_score"],
            "state": "in", "state_label": "live",
            "detail": item.get("match_status"),
            "clock": (f'{item["match_minute"]}\u2032'
                      if item.get("match_minute") is not None else None),
            "period": item.get("match_status"),
            "finished": False, "live": True,
            "provisional": True, "source": "sportybet-via-parse",
        }
        accepted += 1
    return merged, accepted


def infer_published_competition_slugs(games: list[dict]) -> tuple[set[str], int]:
    """Resolve safe ESPN slugs for manually imported bookmaker selections.

    Manually published matches carry a league label, but not always the ESPN
    slug. The previous live reader requested only the slugs already on picks:
    no slug meant no competition was fetched, even for a supported league.

    Only exact unique normalized competition names are mapped. Guessing by
    country alone would attach fixtures from the wrong division/cup.
    """
    from leagues.espn_source import ESPN_CLUB_LEAGUES
    from leagues.results_checker import _normalize_name

    by_name: dict[str, set[str]] = {}
    for slug, display in ESPN_CLUB_LEAGUES.items():
        key = _normalize_name(display)
        if key:
            by_name.setdefault(key, set()).add(slug)
    # Common bookmaker spelling variations map to exactly one verified slug.
    by_name.update({
        "english premier league": {"eng.1"},
        "england premier league": {"eng.1"},
        "english championship": {"eng.2"},
        "championship": {"eng.2"},
        "league one": {"eng.3"},
        "english league one": {"eng.3"},
        "league two": {"eng.4"},
        "english league two": {"eng.4"},
        "saudi pro league": {"sau.1"},
        "saudi professional league": {"sau.1"},
        "saudi premier league": {"sau.1"},
        "egyptian premier league": {"egy.1"},
        "indonesian liga 1": {"idn.1"},
        "spanish la liga": {"esp.1"},
        "italian serie a": {"ita.1"},
        "uefa champions league": {"uefa.champions"},
        "uefa europa league": {"uefa.europa"},
        "uefa conference league": {"uefa.europa.conf"},
        "caf champions league": {"caf.champions"},
    })
    known = set(ESPN_CLUB_LEAGUES)
    slugs: set[str] = set()
    unresolved = 0
    for game in games:
        slug = str(game.get("league_slug") or "")
        if slug in known:
            slugs.add(slug)
            continue
        league = _normalize_name(game.get("league") or "")
        candidates = by_name.get(league, set())
        if len(candidates) == 1:
            slugs.update(candidates)
        else:
            unresolved += 1
    return slugs, unresolved


def _uncached_scores_for_card() -> dict:
    """Scores for every fixture on today's card.

    Dates come from the card's own fixtures, not from the clock. Fetching
    "today and tomorrow" looked right and was wrong: at 02:13 UTC the card
    still carries the previous evening's late kick-offs, that date was never
    requested, and every one of those matches reported no score — which the
    frontend renders as a permanent "in play". Asking for the dates the
    fixtures actually fall on is correct at any hour.

    Only the leagues on the card are fetched, so this stays a handful of
    requests rather than a sweep of all 91.
    """
    try:
        from leagues.daily_feed import build_daily_accumulators

        card = build_daily_accumulators(
            allow_generation=False
        )
        if not card:
            return {"scores": {}, "leagues": [], "dates": [],
                    "published_match_ids": [],
                    "fetched_at": datetime.now(timezone.utc).isoformat()}

        slugs: set[str] = set()
        ids: set[str] = set()
        card_games: list[dict] = []
        dates: set[str] = set()
        for cat in (card.get("accumulators") or {}).values():
            if not isinstance(cat, dict):
                continue
            games = list(cat.get("games") or [])
            for day in cat.get("chain") or []:
                games.extend(day.get("picks") or [])
            for g in games:
                card_games.append(g)
                if g.get("match_id"):
                    ids.add(g["match_id"])
                kickoff = g.get("kickoff") or g.get("commence_time") or ""
                if len(kickoff) >= 10:
                    dates.add(kickoff[:10])

        slugs, competitions_unmapped = infer_published_competition_slugs(card_games)

        # A late kick-off can land in ESPN's next local day, so each fixture
        # date is asked for alongside the day after it.
        wanted: set[str] = set()
        for d in dates:
            try:
                day = datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except Exception:
                continue
            wanted.add((day - timedelta(days=1)).strftime("%Y%m%d"))
            wanted.add(day.strftime("%Y%m%d"))
            wanted.add((day + timedelta(days=1)).strftime("%Y%m%d"))

        found: dict[str, dict] = {}
        for date_str in sorted(wanted):
            found.update(scores_for(sorted(slugs), date_str))

        # Reconcile ESPN's feed ID to the actual locked card without changing
        # the card. Exact IDs win; unmatched IDs require teams and kickoff.
        found, espn_aligned = align_espn_scores_to_card(found, card_games)

        # Optional SportyBet live source extends coverage for games missing
        # from ESPN's live feed. Never use it for official final settlement.
        sporty_status = "disabled"
        sporty_matched = 0
        try:
            from leagues.sportybet_live_feed import snapshot
            observed = snapshot()
            sporty_status = observed.get("status", "unavailable")
            found, sporty_matched = overlay_sportybet_live(
                found, card_games, observed.get("matches") or [],
            )
        except Exception as exc:
            logger.warning("Optional SportyBet live overlay failed: %s",
                           type(exc).__name__)

        # Licensed LiveScore date/live feeds can cover manually published
        # leagues absent from ESPN. Fully gated until commercial rights are
        # confirmed. In all cases these rows are display-only observations.
        livescore_status = "disabled"
        livescore_attached = 0
        try:
            from leagues.authorized_livescore import snapshot as livescore_snapshot
            from leagues.authorized_livescore import overlay as livescore_overlay
            ls = livescore_snapshot(sorted(dates))
            livescore_status = ls.get("status", "unavailable")
            found, livescore_attached = livescore_overlay(
                found, card_games, ls.get("matches") or [],
            )
        except Exception as exc:
            logger.warning("Optional LiveScore scoreboard unavailable: %s",
                           type(exc).__name__)

        resolved = len(ids.intersection(found))
        logger.info(
            "Matchday coverage tracked=%s matched=%s espn_reconciled=%s "
            "sporty=%s livescore=%s unidentified_competitions=%s",
            len(ids), resolved, espn_aligned, sporty_matched,
            livescore_attached, competitions_unmapped,
        )
        return {
            "published_match_ids": sorted(ids),
            "espn_identity_matched": espn_aligned,
            "unmapped_league_games": competitions_unmapped,
            "livescore_source": livescore_status,
            "livescore_live_matched": livescore_attached,
            "matched_fixtures": resolved,
            "missing_score_fixtures": max(0, len(ids) - resolved),
            "sportybet_source": sporty_status,
            "sportybet_live_matched": sporty_matched,
            "tracked_fixtures": len(ids),
            "scores": {k: v for k, v in found.items() if k in ids},
            "leagues": sorted(slugs),
            "dates": sorted(dates),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.warning(f"live scores unavailable: {e}")
        return {"scores": {}, "leagues": [], "dates": [], "error": str(e)}


# Memory + best-effort disk snapshot anchored at the repository root.
# The UI can remain populated when an upstream score service is unavailable.
from leagues.live_snapshot_cache import LiveScoreSnapshot

_LIVE_SCORE_CACHE = LiveScoreSnapshot(ttl_seconds=25)


def scores_for_card() -> dict:
    """Stale-safe public scoreboard; not a source of official settlement."""
    response = _LIVE_SCORE_CACHE.get(_uncached_scores_for_card)
    if (not response.get("scores") and not response.get("dates")
            and not response.get("leagues") and not response.get("tracked_fixtures")):
        # Preserve the original public shape for a legitimately empty card.
        # The internal cache still stores an explicit empty daily snapshot,
        # clearing previous observations without starting any generation.
        return {"scores": {}, "leagues": [], "dates": []}
    return response
