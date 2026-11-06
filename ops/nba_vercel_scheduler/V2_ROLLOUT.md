# NBA private V2 Vercel backup worker (prepared, not released)

The source-only `api/backup-v2.js` handler uses **the existing production scheduler project's secrets** (`CRON_SECRET`, `NBA_BACKUP_JOB_TOKEN`, `BLOB_READ_WRITE_TOKEN`) and private Vercel Blob SDK `put(..., access:'private')` / `get(..., access:'private')`. Never paste secrets into GitHub. Requires `@vercel/blob >=2.3` and a **private** store; it must not be pointed at a public store.

**Safe deployment path:** preserve the current Vercel project's `/api/backup`, `/api/settle`, `/api/forecast`, `/api/market` and their cron schedules. Add `/api/backup-v2` as a *separate route* only after inspecting and reproducing the entire live deployment, secrets metadata, and direct replacement CI. Validate source and private Blob readback before adding a distinct schedule. Do not overwrite the live Vercel project with an incomplete deployment whose other functions are missing. The new Render staging `/api/growth/internal/nba-research/backup-full` and `/backup-full/ack` endpoints must be live first.

**Status:** This file is a tested-ready *source implementation*, not proof of private Blob upload. Require a persisted `verified_full_private_blob_readback` job receipt containing the latest archive/market/audit counts and a fresh separate-db restore before approving rollback.

Neither original Render DB nor current Supabase DB should ever be overwritten during a drill.
