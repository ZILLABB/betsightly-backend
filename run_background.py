"""Run one BetSightly background process role."""

import os
import time

role = os.getenv(
    "BETSIGHTLY_PROCESS_ROLE",
    "",
).strip().lower()

if role not in {
    "scheduler",
    "telegram",
}:
    raise SystemExit(
        "Set BETSIGHTLY_PROCESS_ROLE="
        "scheduler or telegram"
    )

# main starts only the loops belonging to
# the selected role.
import main  # noqa: F401,E402

while True:
    time.sleep(3600)
