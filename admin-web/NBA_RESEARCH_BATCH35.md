BetSightly Batch 35 — Private NBA Command Center

This change affects only the existing Vercel admin source at admin-web/. It is based on the current devil commit but stays on a separate feature branch. Public football and football admin production routes remain unchanged.

Vercel project: betsightly-admin (repo ZILLABB/betsightly-backend, Vite application admin-web). Default-off flag for frontend: VITE_NBA_RESEARCH_ADMIN_ENABLED=true is required to show the tab. Login is still mandatory. The existing same-origin Vercel BFF accepts a read-only GET for admin/nba-research, not any NBA mutation.

The page requests a verified canonical response from the backend containing recorded moneyline, original score, advanced score and verified final state. It displays a premium Atlantic read-only dashboard with counts, WAT fixture times, source-model comparisons, status filters, copy and CSV export. All loading, access-denied, empty and unreachable-backend states are explicit. It does not invent the user's 16 locally recorded NBA games or create SportyBet codes.

CONNECTION NOT YET COMPLETE: the research branch and original signed NBA ledgers currently exist only on the owner's Windows checkout. The Render backend does not automatically have these files; the GET route does not exist on the current deployed devil backend. A separate authenticated backend API, durable store of the signed original records and verified settlement data, and server-side NBA_ADMIN_RESEARCH_ENABLED gate are needed before enabling even the preview. Browser flags alone are not authorization. Data licensing review is still outstanding.

Acceptance: node tests, TypeScript check, Vite build, backend auth/ledger integrity tests, preview-only validation, then deliberate release. Do not merge this change to devil or deploy to football/production automatically. The NBA game list and SportyBet code builder are independent workflows.
