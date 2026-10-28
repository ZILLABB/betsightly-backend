"""Read-only source-to-archive NBA coverage auditing."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from basketball.research_private_bundle import inspect_bundle

HORIZON_HOURS = 48
EXTENDED_DAYS = 7
