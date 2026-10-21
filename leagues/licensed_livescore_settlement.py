"""License-gated final-score adapter for broader LiveScore coverage.

The consumer LiveScore CDN does not grant commercial settlement rights by
default. Do not enable this adapter without documented commercial permission
that includes automated score retrieval/reuse *and* a reviewed field contract
proving the regulation-time final score. No proxying or anti-bot workarounds.

Unknown, missing, contradictory and extra-time scores are rejected rather
than guessing. The common settlement evaluator continues to enforce 1X2,
goals and result-status rules.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import logging
import os

LOG = logging.getLogger(__name__)


def licensed_for_settlement() -> bool:
    from leagues.authorized_livescore import enabled

    truthy = {"1", "true", "yes"}
    return (enabled()
            and os.getenv("LIVESCORE_SETTLEMENT_LICENSE_VERIFIED", "").lower() in truthy
            and os.getenv("LIVESCORE_90MIN_FIELDS_VERIFIED", "").lower() in truthy)


def _when(raw: object) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(raw or "").replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        return None


def _regulation_score(observation: dict) -> tuple[int, int] | None:
    """Require explicitly verified FT + regulation fields; never infer ET."""
    if (observation.get("source") != "livescore-cdn"
            or observation.get("finished") is not True
            or observation.get("live") is True
            or observation.get("state") != "post"
            or str(observation.get("detail") or "").upper() not in {"FT", "FULL TIME"}):
        return None
    h = observation.get("regulation_home_score")
    a = observation.get("regulation_away_score")
    hf = observation.get("home_score")
    af = observation.get("away_score")
    if (any(isinstance(n, bool) or not isinstance(n, int) or n < 0 or n > 99
            for n in (h, a, hf, af))
            or (h, a) != (hf, af)):
        # A discrepancy could indicate extra-time or a corrected score. AET
        # and penalties cannot be accepted for 90-minute accumulator grading.
        return None
    return h, a


def licensed_livescore_finals(
    picks: list[dict], *, now: datetime | None = None,
) -> list[dict]:
    """Return only unambiguous, same-team, same-kickoff confirmed FT rows."""
    if not licensed_for_settlement() or not picks:
        return []

    from leagues.authorized_livescore import snapshot
    from leagues.results_checker import _normalize_name

    current = now or datetime.now(timezone.utc)
    due: dict[tuple[str, str, str], list[datetime]] = defaultdict(list)
    for pick in picks:
        if pick.get("status") in {"won", "lost", "void"}:
            continue
        kickoff = _when(pick.get("commence_time") or pick.get("kickoff") or pick.get("date"))
        if (kickoff is None or kickoff + timedelta(minutes=80) > current
                or kickoff < current - timedelta(days=2)):
            continue
        home = _normalize_name(pick.get("home_team"))
        away = _normalize_name(pick.get("away_team"))
        if home and away:
            due[(home, away, kickoff.date().isoformat())].append(kickoff)
    if not due:
        return []

    dates = sorted({d for _, _, d in due})
    if len(dates) > 3:
        return []
    report = snapshot(dates)
    if report.get("status") not in {"ok", "partial"}:
        return []

    candidates: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for observation in report.get("matches") or []:
        if not isinstance(observation, dict):
            continue
        score = _regulation_score(observation)
        kickoff = _when(observation.get("kickoff_utc"))
        if score is None or kickoff is None:
            continue
        home = _normalize_name(observation.get("home_team"))
        away = _normalize_name(observation.get("away_team"))
        identity = (home, away, kickoff.date().isoformat())
        if identity not in due:
            continue
        if not any(abs((kickoff - original).total_seconds()) <= 20 * 60
                   for original in due[identity]):
            continue
        provider_id = str(observation.get("provider_event_id") or "")
        if not provider_id.isdecimal() or not provider_id:
            continue
        candidates[identity].append({
            "home": observation["home_team"],
            "away": observation["away_team"],
            "date": identity[-1],
            "home_score": score[0], "away_score": score[1],
            "score_90": {"home": score[0], "away": score[1]},
            "completed": True,
            "match_status": "STATUS_FULL_TIME",
            "provider": "livescore-licensed",
            "provider_event_id": provider_id,
        })

    accepted = [rows[0] for rows in candidates.values() if len(rows) == 1]
    LOG.info("Licensed LiveScore final lookup candidates=%s verified=%s",
             len(candidates), len(accepted))
    return accepted
