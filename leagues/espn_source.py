"""
ESPN fixture + odds source.

ESPN's public scoreboard carries real DraftKings prices (moneyline for
home/draw/away plus an over/under line with both sides) on essentially every
scheduled fixture, alongside kickoff time, venue, recent form and season
records. That removes the dependency on the paid Odds API, whose free quota
has been exhausted since June.

It also fixes the coverage collapse. The previous pipeline required both
teams to exist in the 767-team ELO registry and dropped the fixture
otherwise — which discarded 85% of fixtures, because that registry never
covered Argentine Nacional B, the Bolivian or Peruvian leagues, and most of
the rest of the world. Here, odds are the primary signal and ELO is an
optional second opinion, so no fixture is dropped for want of a rating.

Odds arrive as American prices and are converted to decimal, then de-vigged
(normalised so the three outcome probabilities sum to 1) before use.
"""

import hashlib
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from leagues.competition_registry import provider_slugs, tournament_context

logger = logging.getLogger(__name__)

from leagues.cache_paths import cache_path

CACHE_PATH = cache_path(
    Path(__file__).parent.parent / "cache" / "espn_fixtures.json"
)
CACHE_TTL = 3 * 3600  # 3 hours — odds drift, but not minute to minute
CACHE_SCHEMA_VERSION = 2

SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard"

# Compatibility name retained for existing callers. The registry is now the
# only source of truth and includes club and international competitions.
ESPN_CLUB_LEAGUES = provider_slugs()
ESPN_COMPETITIONS = ESPN_CLUB_LEAGUES
_FETCH_HEALTH: dict[str, dict] = {}
_LAST_CACHE_METADATA: dict = {}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _registry_version(leagues: dict | None = None) -> str:
    names = sorted((leagues or ESPN_CLUB_LEAGUES).keys())
    return hashlib.sha256("|".join(names).encode()).hexdigest()[:12]


def cache_metadata() -> dict:
    """Metadata for the fixture snapshot returned by the latest call."""
    return dict(_LAST_CACHE_METADATA)


def _parse_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _filter_window(fixtures: list[dict], start: datetime,
                   end: datetime) -> list[dict]:
    filtered = []
    for fixture in fixtures:
        kickoff = _parse_time(fixture.get("commence_time"))
        if kickoff is not None and start <= kickoff <= end:
            filtered.append(fixture)
    return sorted(filtered, key=lambda fixture: fixture["commence_time"])


def _cache_covers(payload: dict, start: datetime, end: datetime) -> bool:
    metadata = payload.get("metadata") or {}
    cached_start = _parse_time(metadata.get("coverage_start"))
    cached_end = _parse_time(metadata.get("coverage_end"))
    return bool(
        payload.get("schema_version") == CACHE_SCHEMA_VERSION
        and metadata.get("complete") is True
        and cached_start is not None and cached_end is not None
        and cached_start <= start and cached_end >= end
        and metadata.get("registry_version") == _registry_version()
        and set(metadata.get("leagues_requested") or [])
        == set(ESPN_CLUB_LEAGUES)
    )


# ── Odds helpers ───────────────────────────────────────────

def _american_to_decimal(american) -> float | None:
    """Convert an American moneyline price to decimal odds."""
    try:
        a = float(str(american).replace("+", "").strip())
    except (TypeError, ValueError):
        return None
    if a == 0:
        return None
    return round(1.0 + (100.0 / abs(a) if a < 0 else a / 100.0), 3)


def _devig(probs: dict[str, float]) -> dict[str, float]:
    """Normalise implied probabilities so they sum to 1 (strip bookmaker margin)."""
    total = sum(v for v in probs.values() if v)
    if total <= 0:
        return {}
    return {k: v / total for k, v in probs.items() if v}


def _parse_odds(competition: dict) -> dict:
    """Extract decimal odds + de-vigged probabilities from an ESPN competition.

    Returns {} when the fixture carries no usable prices.
    """
    blocks = [b for b in (competition.get("odds") or []) if isinstance(b, dict)]
    if not blocks:
        return {}
    o = blocks[0]

    # 1X2 moneylines. ESPN nests these as moneyline.{home,away}.{close,open}.odds
    # (closing price preferred), with the draw carried separately on drawOdds.
    # Older payloads instead expose {home,away}TeamOdds.moneyLine, so try both.
    def _phase_odds(node) -> object | None:
        if not isinstance(node, dict):
            return None
        for phase in ("close", "open", "current"):
            p = node.get(phase)
            if isinstance(p, dict) and p.get("odds") is not None:
                return p["odds"]
        return node.get("odds")

    ml = o.get("moneyline") or {}
    home_ml = _phase_odds(ml.get("home"))
    away_ml = _phase_odds(ml.get("away"))
    draw_ml = _phase_odds(ml.get("draw"))

    if home_ml is None:
        home_ml = (o.get("homeTeamOdds") or {}).get("moneyLine")
    if away_ml is None:
        away_ml = (o.get("awayTeamOdds") or {}).get("moneyLine")
    if draw_ml is None:
        draw_ml = (o.get("drawOdds") or {}).get("moneyLine")

    home_dec = _american_to_decimal(home_ml)
    away_dec = _american_to_decimal(away_ml)
    draw_dec = _american_to_decimal(draw_ml)

    # Over/under. Prefer the closing price, fall back to opening.
    total = o.get("total") or {}
    line = o.get("overUnder")

    def _ou(side: str):
        node = total.get(side) or {}
        for phase in ("close", "open"):
            p = node.get(phase) or {}
            dec = _american_to_decimal(p.get("odds"))
            if dec:
                return dec
        return None

    over_dec, under_dec = _ou("over"), _ou("under")

    out = {
        "provider": (o.get("provider") or {}).get("displayName"),
        "line": line,
        "home_win": home_dec, "draw": draw_dec, "away_win": away_dec,
    }

    if line is not None and float(line) == 2.5:
        out["over_2_5"] = over_dec
        out["under_2_5"] = under_dec

    # De-vigged 1X2 probabilities
    if home_dec and away_dec:
        raw = {"home_win": 1.0 / home_dec, "away_win": 1.0 / away_dec}
        if draw_dec:
            raw["draw"] = 1.0 / draw_dec
        out["implied"] = {k: round(v, 4) for k, v in _devig(raw).items()}

    # De-vigged over/under probabilities
    if over_dec and under_dec:
        ou = _devig({"over": 1.0 / over_dec, "under": 1.0 / under_dec})
        out["implied_over"] = round(ou.get("over", 0), 4)
        out["implied_under"] = round(ou.get("under", 0), 4)
        out["ou_line"] = float(line) if line is not None else None

    return out


# ── Fixture fetching ───────────────────────────────────────

def _fetch_league(slug: str, date_range: str) -> list[dict]:
    """Scheduled fixtures for one league across a date range (single request)."""
    try:
        resp = requests.get(
            SCOREBOARD.format(slug=slug),
            params={"dates": date_range, "limit": 500}, timeout=25,
        )
        if resp.status_code != 200:
            _FETCH_HEALTH[slug] = {
                "provider_active": False,
                "request_succeeded": False,
                "error": f"HTTP {resp.status_code}",
            }
            return []
        payload = resp.json()
    except Exception as e:
        _FETCH_HEALTH[slug] = {
            "provider_active": False,
            "request_succeeded": False,
            "error": str(e)[:180],
        }
        logger.debug(f"ESPN fetch failed {slug}: {e}")
        return []

    league_name = ESPN_CLUB_LEAGUES.get(slug) or (payload.get("leagues") or [{}])[0].get("name", slug)
    out = []
    for ev in payload.get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        if comp.get("status", {}).get("type", {}).get("name") != "STATUS_SCHEDULED":
            continue
        teams = comp.get("competitors", [])
        home = next((t for t in teams if t.get("homeAway") == "home"), None)
        away = next((t for t in teams if t.get("homeAway") == "away"), None)
        if not home or not away:
            continue

        commence = ev.get("date", "")
        if commence.endswith("Z") and len(commence) == 17:  # 2026-07-31T23:30Z
            commence = commence[:-1] + ":00Z"
        if not commence:
            continue

        def team_info(c: dict) -> dict:
            t = c.get("team", {}) or {}
            rec = ""
            for r in (c.get("records") or []):
                if r.get("type") == "total":
                    rec = r.get("summary", "")
                    break
            return {
                "id": t.get("id"),
                "uid": t.get("uid"),
                "name": t.get("displayName", ""),
                "short": t.get("shortDisplayName", ""),
                "abbrev": t.get("abbreviation", ""),
                "logo": t.get("logo"),
                "form": c.get("form"),      # e.g. "WWLLD"
                "record": rec,              # e.g. "7-4-6"
            }

        venue = comp.get("venue") or {}
        addr = venue.get("address") or {}
        broadcasts = []
        for b in (comp.get("broadcasts") or []):
            broadcasts.extend(b.get("names") or [])

        h, a = team_info(home), team_info(away)
        context = tournament_context(slug, ev, comp)
        out.append({
            "event_id": ev.get("id"),
            "league_slug": slug,
            "league": league_name,
            "commence_time": commence,
            "home": h,
            "away": a,
            "venue": {
                "name": venue.get("fullName"),
                "city": addr.get("city"),
                "country": addr.get("country"),
            },
            "broadcast": broadcasts,
            "odds": _parse_odds(comp),
            "competition": context,
            **{key: context.get(key) for key in (
                "competition_type", "region", "team_type", "stage", "round",
                "leg_number", "knockout", "neutral_venue", "context_label",
            )},
        })
    _FETCH_HEALTH[slug] = {
        "provider_active": bool(payload.get("leagues")),
        # A valid empty scoreboard is still a complete provider response. It
        # must not poison the wide cache merely because this league has no
        # scheduled fixture inside the requested window.
        "request_succeeded": True,
        "scheduled_fixture_count": len(out),
        "last_successful_fetch": datetime.now(timezone.utc).isoformat(),
        "error": None,
    }
    return out


def fetch_health() -> dict[str, dict]:
    """Last in-process provider health, keyed by competition slug."""
    return {slug: dict(value) for slug, value in _FETCH_HEALTH.items()}


def get_fixtures(days_ahead: int = 3, force: bool = False,
                 now: datetime | None = None) -> list[dict]:
    """All scheduled fixtures with odds across every tracked league. Cached."""
    global _LAST_CACHE_METADATA
    days_ahead = max(1, min(14, int(days_ahead)))
    now = now or _utcnow()
    requested_end = now + timedelta(days=days_ahead)
    if not force and CACHE_PATH.exists():
        try:
            if time.time() - CACHE_PATH.stat().st_mtime < CACHE_TTL:
                cached = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
                if isinstance(cached, dict) and _cache_covers(
                        cached, now, requested_end):
                    fixtures = _filter_window(
                        cached.get("fixtures") or [], now, requested_end
                    )
                    _LAST_CACHE_METADATA = {
                        **(cached.get("metadata") or {}),
                        "cache_hit": True,
                        "requested_days": days_ahead,
                        "returned_fixture_count": len(fixtures),
                    }
                    return fixtures
        except Exception:
            pass

    date_range = f"{now.strftime('%Y%m%d')}-{(now + timedelta(days=days_ahead)).strftime('%Y%m%d')}"

    for slug in ESPN_CLUB_LEAGUES:
        _FETCH_HEALTH.pop(slug, None)
    fixtures: list[dict] = []
    pending = list(ESPN_CLUB_LEAGUES)
    for retry_round in range(3):
        if not pending:
            break
        if retry_round:
            time.sleep(.15 * retry_round)
        attempted = list(pending)
        with ThreadPoolExecutor(max_workers=min(16, len(attempted))) as pool:
            chunks = list(pool.map(
                lambda slug: _fetch_league(slug, date_range), attempted
            ))
        for chunk in chunks:
            fixtures.extend(chunk)
        # `_fetch_league` marks a valid empty scoreboard successful, so only
        # transport/provider failures enter the next bounded retry round.
        pending = [
            slug for slug in attempted
            if not (_FETCH_HEALTH.get(slug) or {}).get("request_succeeded")
        ]

    # Provider registries occasionally overlap competitions. Preserve the
    # first normalized fixture and never let retries or overlap duplicate it.
    unique = {}
    for fixture in fixtures:
        key = (
            str((fixture.get("home") or {}).get("name") or "").casefold(),
            str((fixture.get("away") or {}).get("name") or "").casefold(),
            str(fixture.get("commence_time") or ""),
        )
        unique.setdefault(key, fixture)
    fixtures = list(unique.values())

    # Drop fixtures that already kicked off
    fixtures = _filter_window(fixtures, now, requested_end)

    for f in fixtures:
        f["match_id"] = hashlib.md5(
            f"{f['home']['name']}{f['away']['name']}{f['commence_time']}".encode()
        ).hexdigest()

    successful = sorted(
        slug for slug in ESPN_CLUB_LEAGUES
        if (_FETCH_HEALTH.get(slug) or {}).get("request_succeeded")
    )
    failed = sorted(slug for slug in ESPN_CLUB_LEAGUES if slug not in successful)
    metadata = {
        "generated_at": _utcnow().isoformat(),
        "requested_days": days_ahead,
        "coverage_start": now.isoformat(),
        "coverage_end": requested_end.isoformat(),
        "leagues_requested": sorted(ESPN_CLUB_LEAGUES),
        "successful_leagues": successful,
        "failed_leagues": failed,
        "fixture_count": len(fixtures),
        "complete": not failed,
        "successful_league_count": len(successful),
        "requested_league_count": len(ESPN_CLUB_LEAGUES),
        "failed_league_count": len(failed),
        "registry_version": _registry_version(),
        "cache_hit": False,
        "returned_fixture_count": len(fixtures),
    }
    _LAST_CACHE_METADATA = metadata
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps({
            "schema_version": CACHE_SCHEMA_VERSION,
            "metadata": metadata,
            "fixtures": fixtures,
        }, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass

    with_odds = sum(1 for f in fixtures if f["odds"].get("implied"))
    logger.info(
        "ESPN: %s fixtures across %s/%s leagues (%s priced, complete=%s)",
        len(fixtures), len(successful), len(ESPN_CLUB_LEAGUES), with_odds,
        metadata["complete"],
    )
    return fixtures
