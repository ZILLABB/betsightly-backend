"""Private on-return notifications for anonymous Builder prediction wins.

The anonymous per-browser UUID is a high-entropy bearer capability, not a
login or a claim that a customer wagered. Never expose another visitor's
tickets; never include the raw visitor ID in analytics or public GET URLs.
This is read-only against pre-existing immutable prediction settlements.
"""
from __future__ import annotations

import re
import logging
from sqlalchemy import text

LOG = logging.getLogger(__name__)

# Existing frontend generates anon_ + crypto.randomUUID(): 122 bits entropy.
# Non-cryptographic legacy fallbacks cannot access private notifications.
_PRIVATE_ID = re.compile(
    r"^anon_[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$", flags=re.I,
)

# Matching sorted selection IDs also verifies the entire ticket and its
# market choices, not merely matching team names / individual fixtures.
# Verified against existing production user and Builder records.
_WIN_SQL = text("""
    WITH visitor_tickets AS (
      SELECT h.id, h.created_at, h.generated_odds, h.booking_validated,
             ARRAY_AGG(s.selection_fingerprint::text
                       ORDER BY s.selection_fingerprint::text) AS selected,
             COUNT(s.id) AS leg_count
      FROM user_ticket_history h
      JOIN user_ticket_selections s ON s.ticket_id = h.id
      WHERE h.anonymous_id = :visitor
        AND h.created_at >= (now() - interval '30 days')
        AND h.booking_validated IS TRUE
      GROUP BY h.id
    ), won_sets AS (
      SELECT p.settled_at,
             ARRAY(
               SELECT leg->>'selection_id'
               FROM jsonb_array_elements(p.picks::jsonb) leg
               ORDER BY leg->>'selection_id'
             ) AS selected
      FROM builder_predictions p
      WHERE p.final_status = 'won'
        AND p.settled_at IS NOT NULL
        AND p.created_at >= (now() - interval '60 days')
    )
    SELECT t.id AS ticket_id, t.created_at AS generated_at,
           t.generated_odds AS prediction_odds, t.leg_count,
           MAX(w.settled_at) AS settled_at
    FROM visitor_tickets t
    JOIN won_sets w ON t.selected = w.selected
    WHERE ARRAY_LENGTH(t.selected, 1) = t.leg_count
      AND NOT ARRAY_POSITION(t.selected, NULL) IS NOT NULL
    GROUP BY t.id, t.created_at, t.generated_odds, t.leg_count
    ORDER BY MAX(w.settled_at) DESC, t.created_at DESC
    LIMIT :limit
""")

def validate_visitor_id(value: str | None) -> bool:
    return isinstance(value, str) and bool(_PRIVATE_ID.fullmatch(value))


def winning_notifications(anonymous_id: str | None, *, limit: int = 25) -> dict:
    """Resolve only this browser's won Builder prediction sets, with no PII.

    Missing/malformed IDs return the same empty response rather than allowing
    enumeration. This never marks a bet 'placed', 'copied', or 'played'.
    """
    result = {"status": "success", "predictions_only": True,
              "notifications": []}
    if not validate_visitor_id(anonymous_id):
        return result
    from database import engine
    try:
        with engine.connect() as conn:
            rows = conn.execute(_WIN_SQL, {
                "visitor": anonymous_id, "limit": max(1, min(int(limit), 30)),
            }).mappings().all()
    except Exception as exc:
        LOG.warning("Private Builder win lookup unavailable type=%s",
                    type(exc).__name__)
        return {"status": "unavailable", "predictions_only": True,
                "notifications": []}
    for row in rows:
        result["notifications"].append({
            "ticket_id": row["ticket_id"],
            "generated_at": (
                row["generated_at"].isoformat()
                if row["generated_at"] else None
            ),
            "won_at": (
                row["settled_at"].isoformat()
                if row["settled_at"] else None
            ),
            "prediction_odds": row["prediction_odds"],
            "leg_count": row["leg_count"],
            "status": "won",
            "wager_confirmed": False,
        })
    return result
