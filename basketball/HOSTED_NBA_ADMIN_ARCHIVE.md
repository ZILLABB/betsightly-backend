# BetSightly NBA: Secure Hosted Research Archive (Draft Only)

Draft research PR #178 and existing Vercel Command Center PR #180 remain unmerged and undeployed.

Local researcher exports only the original signed game-specific pre-tipoff forecasts,
verified finals and matching source fixtures; no large historical training files.
Command from the Windows NBA checkout:

    git pull --ff-only origin stage1/nba-private-research-20261024
    python -m basketball.research_cli archive-export

Default resulting file: data/basketball/research/nba_admin_export.json.
Private original evidence. DO NOT commit it, email it or paste it in public chat.

Server uses the existing administrator HttpOnly cookie, and requires BOTH
NBA_ADMIN_RESEARCH_ENABLED=true and NBA_ADMIN_RESEARCH_IMPORT_ENABLED=true
before accepting a bounded import. The GET endpoint needs only the first
flag. The frontend tab has another default-off build-time flag,
VITE_NBA_RESEARCH_ADMIN_ENABLED=true. These flags are NOT enabled now.

Only scoped NBA-private Postgres table nba_private_research_snapshots is
created. The complete SHA256-fingerprinted original payload is immutable.
A second import can add forecasts and verified finals, but cannot delete or
change an old forecast, settlement, match identity or confirmed final score.
Unchanged re-imports are idempotent. On every GET the source NBA fixture
identities, hashes and pregame cutoffs are validated and a readback digest
is returned. The Atlantic admin upload shows success only after that exact
digest is returned by a fresh authenticated GET.

Neither original forecasts nor football results are updated or published.
Bookmaker odds and basketball SportyBet booking codes are not generated.

LIMITATION: The 16 genuine NBA forecasts currently exist only on the user's
Windows computer. No tool in this chat can read that local folder or upload
its file without the user's own later export/import action.
Cloud historical data usage rights and staging DB verification remain open.
Do not enable flags or deploy directly to football production before
auth, persistent storage, retention, cost, and rollback checks pass.

SHA256 protects change detection; because the file is self-hashed, it
cannot independently prove the wall-clock time of original capture.