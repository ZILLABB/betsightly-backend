"""Deliberate activation barrier for *new* dedicated VPS worker roles.

A text acknowledgement is not proof the old Render worker is stopped.
The operator must separately verify the cutover to avoid dual writers.
Legacy worker/scheduler roles retain their old behavior while preparing.
"""

from __future__ import annotations


APPROVED_TOKEN = "render-fenced-and-approved"
DEDICATED_VPS_WRITERS = frozenset({"publication", "settlement", "telegram"})


def require_writer_activation(role: str, configured_value: str | None) -> None:
    if role in DEDICATED_VPS_WRITERS and configured_value != APPROVED_TOKEN:
        raise SystemExit(
            "VPS role activation refused: verify existing Render writers "
            "are stopped before explicitly approving cutover"
        )
