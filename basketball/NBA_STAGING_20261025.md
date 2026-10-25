# BetSightly NBA isolated staging — October 25, 2026

## Created and verified (NOT production)
- Render workspace: My Workspace `tea-d8hj4ek8aovs73ah57vg`.
- NBA staging API: `srv-dbf7vde7bikc73ch5gg0`, `betsightly-nba-research-stage-20261025`, on the **research draft** branch `stage1/nba-private-research-20261024`; free service, Docker, auto-deploy **off**, initial deploy and admin-auth env restart both **live**.
- URL: `https://betsightly-nba-research-stage-20261025.onrender.com`.
- Isolated NEW staging database: `dpg-dbf7ufe7bikc73ch25m0-a`, `betsightly-nba-stage-20261025` in Oregon, **free and available**, due to **expire on 2026-11-24 at 22:14 UTC**. It is not attached yet. A prior expired `betsightly-db-staging` remains suspended; do not resurrect or pay for it.
- Vercel preview deployment: `dpl_6sfj1u6oFMeKxcaCwubvbM5isYdR`, READY, `https://betsightly-admin-pj6domtfd-zillabbs-projects.vercel.app`, branch `feature/nba-admin-research-20261025` from **admin draft PR #180**.
- Preview-only, branch-specific Vercel env variables: `VITE_NBA_RESEARCH_ADMIN_ENABLED=true` and `ADMIN_BACKEND_ORIGIN=https://betsightly-nba-research-stage-20261025.onrender.com`; verified. Live admin global `ADMIN_BACKEND_ORIGIN=https://betsightly-api.onrender.com` **unchanged**.
- Staging Render environment: `ENVIRONMENT=staging`, `ENABLE_BACKGROUND_JOBS=false`, `NBA_ADMIN_RESEARCH_ENABLED=false`, `NBA_ADMIN_RESEARCH_IMPORT_ENABLED=false`, separate staging-only `SECRET_KEY` and `ADMIN_PASSWORD_HASH`. Never use production secrets.

## Remaining controlled connection: no secret in chat
Render MCP provides Postgres resource metadata but **not its internal connection password or URL**. To connect it, open:
1. Database `https://dashboard.render.com/d/dpg-dbf7ufe7bikc73ch25m0-a` → Connect → copy **Internal Database URL** (no screenshots, logs, GitHub, chat messages or source-code commitments containing the credential).
2. Isolated API `https://dashboard.render.com/web/srv-dbf7vde7bikc73ch5gg0` → Environment → set only **DATABASE_URL** equal to that internal URL; save and allow its own staging-only redeploy. Do **not** use `betsightly-db` production credentials. Do not alter live `betsightly-api`.
3. Verify DB connection and signed snapshots first; only afterward enable server flags `NBA_ADMIN_RESEARCH_ENABLED=true` and `NBA_ADMIN_RESEARCH_IMPORT_ENABLED=true` on staging API. The Vercel feature branch has its own enabling flag. Any import is still admin-cookie protected, schema and SHA256 checked, append-only, and requires successful digest readback.
4. Local researcher (Windows) after pulling this branch runs `python -m basketball.research_cli archive-export`. The resulting **private** file `data/basketball/research/nba_admin_export.json` must be imported ONLY through the stage preview NBA Research page when it is connected. Keep local original records; verify 16 moneyline, 16 original score and 16 advanced score entries, all on 16 distinct game IDs, then compare staged results with local read-only reports.
5. Publish no football predictions or SportyBet codes via the staging preview. Production `devil`, Vercel main admin domain and real Postgres `betsightly-db` remain untouched.

## Safety / cost / limitations
- Both newly created Render staging resources explicitly have **free** plans. Render Free Postgres has **1GB, no backups, one active free DB per workspace, 30-day expiration and 14-day upgrade grace**. Do not use as the only durable research evidence.
- Free Render web instances have finite monthly workspace hours and can spin down; don't claim an always-on settlement worker. Staging backend background jobs are deliberately disabled.
- The preview is temporary, not a public basketball launch. Do not merge PR #178/#180 or PR #179 solely to make a preview.
- Render staging API may boot with default ephemeral local SQLite until its isolated **DATABASE_URL** is configured. That does not mean the new Postgres is connected. Do not import any forecasts before Postgres is confirmed.
- The published historical advanced-model improvements have not been shown statistically significant; no verified bookmaker lines or genuine SportyBet codes.
