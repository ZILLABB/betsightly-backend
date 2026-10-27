BetSightly Batch 35 — Private NBA Command Center

This change affects only the existing Vercel admin source at admin-web/. It is based on the current devil commit but stays on a separate feature branch. Public football and football admin production routes remain unchanged.

Vercel project: betsightly-admin (repo ZILLABB/betsightly-backend, Vite application admin-web). Default-off flag for frontend: VITE_NBA_RESEARCH_ADMIN_ENABLED=true is required to show the tab. Login is still mandatory. The existing same-origin Vercel BFF accepts a read-only GET for admin/nba-research, not any NBA mutation.

The page requests a verified canonical response from the backend containing recorded moneyline, original score, advanced score and verified final state. It displays a premium Atlantic read-only dashboard with counts, WAT fixture times, source-model comparisons, status filters, copy and CSV export. All loading, access-denied, empty and unreachable-backend states are explicit. It does not invent the user's 16 locally recorded NBA games or create SportyBet codes.

CONNECTION NOT YET COMPLETE: the research branch and original signed NBA ledgers currently exist only on the owner's Windows checkout. The Render backend does not automatically have these files; the GET route does not exist on the current deployed devil backend. A separate authenticated backend API, durable store of the signed original records and verified settlement data, and server-side NBA_ADMIN_RESEARCH_ENABLED gate are needed before enabling even the preview. Browser flags alone are not authorization. Data licensing review is still outstanding.

Acceptance: node tests, TypeScript check, Vite build, backend auth/ledger integrity tests, preview-only validation, then deliberate release. Do not merge this change to devil or deploy to football/production automatically. The NBA game list and SportyBet code builder are independent workflows.


## Batch 36 — Hosted snapshot import via the existing Vercel admin

The companion private backend in research PR #178 now includes a complete protected, default-off POST import route, isolated SQL snapshots, original SHA256/time-of-capture validation, a read-only DB dashboard, and an export command for the 16 local NBA forecasts. The live production devil backend still does not have this route because no pull request has been merged or deployed.

The NBA Research page now has Import research archive, which accepts the local export JSON up to 750KB through the existing same-origin proxy. Every existing mutation retains the original 16KB body limit. The frontend accepts an import as confirmed only after a fresh GET returns the exact database SHA256 digest from the POST response. Upload errors show explicit retry/readback warnings, never a false published state.

Configuration is split deliberately: frontend flag VITE_NBA_RESEARCH_ADMIN_ENABLED=true only exposes the tab; backend flags NBA_ADMIN_RESEARCH_ENABLED=true (GET) and NBA_ADMIN_RESEARCH_IMPORT_ENABLED=true (POST) separately authorize storage access. All are disabled by default. The current 16 forecasts cannot appear on Vercel until the owner exports them from Windows and imports them to an approved private/staging deployment.

Use the unmerged PRs for controlled staging verification; do not send private JSONL files to GitHub, email, Telegram or public APIs. No SportyBet code is produced. No public football site code was changed.

## Reconciled private-preview deployment (2026-10-27)
This branch was replayed onto current `devil`, preserving merged Basketball
Jackpot readback/recovery code, the production proxy's safe GET retries and all
existing football routes. Previous draft PR #180 remains unmerged.

Vercel **branch-only preview** configuration for this exact branch:
`VITE_NBA_RESEARCH_STAGING_ONLY=true`,
`VITE_NBA_RESEARCH_ADMIN_ENABLED=true`, and
`ADMIN_BACKEND_ORIGIN=https://betsightly-nba-research-stage-20261025.onrender.com`.
Never copy these staging settings into production. The proxy denies all football
and basketball booking paths when it is pointing at the NBA staging backend.
A fresh deployment after these environment changes is required to test the
research-only navigation and signed archive/market history readback.
