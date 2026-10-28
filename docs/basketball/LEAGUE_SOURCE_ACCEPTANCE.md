# BetSightly: six non-NBA league source acceptance

Status: 2026-10-28. **Research-source availability verified, not a commercial
basketball data licence or approved prediction model.** This document fixes
the repeated confusion between source discovery, complete historical ingestion
and public prediction readiness.

## Single source registry

Private, staging-only endpoint:
`GET /api/growth/admin/nba-research/league-source-matrix`.

The six candidate sources are listed in
`basketball/research_league_source_catalog.py`. The administrative endpoints
are protected by existing Render-backed admin authentication.

| League | Source pilot | Independently check against | Rights |
|---|---|---|---|
| WNBA | ESPN basketball/wnba/scoreboard, fixed date | WNBA.com | https://www.wnba.com/terms-of-use |
| NCAA men | ESPN basketball/mens-college-basketball/scoreboard | NCAA.com Division I scoreboard | https://www.ncaa.com/tos |
| NCAA women | ESPN basketball/womens-college-basketball/scoreboard | NCAA.com Division I scoreboard | https://www.ncaa.com/tos |
| Australian NBL | ESPN basketball/nbl/scoreboard | https://www.nbl.com.au/schedule | Confirm commercial terms with NBL/ESPN |
| EuroLeague | api-live.euroleague.net/v2/competitions/E/seasons/E{year}/games | Licensed alternative/official schedule | https://inform.euroleague.net/terms |
| EuroCup | api-live.euroleague.net/v2/competitions/U/seasons/U{year}/games | Licensed alternative/official schedule | https://inform.euroleague.net/terms |

**Live read-only connectivity (28 October 2026)**: all six returned HTTP
200. WNBA 2026-08-01: 2 games, 2 candidate finals. NCAA men/women
2026-03-20: 16 games each, all returned as finals. NBL 2026-10-28:
1 scheduled fixture. EuroLeague E2026: page count 380/total 380;
EuroCup U2026: page count 224/total 224. This is a bounded one-off
probe, **not** 380 or 224 verified independent final scores.

Reachability can regress; no source is assumed live in a later request.
ESPN and NBA/WNBA rights remain different from an open data licence;
Euroleague terms prohibit gambling-related reuse without authorisation.
FIBA GDAP is subscription/authentication-based and is not a free
commercial fallback: https://gdap-portal.fiba.basketball/documentation

## What exists now

- Four ESPN-based basketball league candidate adapters (WNBA, NCAA men,
  NCAA women and Australian NBL). Exact team/event/UTC identities are
  validated for scheduled or final games. Original source responses are
  not written into the NBA archive.
- Two bounded European season-listing adapters. Full response count
  matching is a *page-completeness* result only, not a final-score
  settlement verification.
- A private source-catalog endpoint and two existing admin-only probe
  endpoints: `league-sources?league=nbl_au&day=20261028` and
  `europe-sources?league=euroleague&start_year=2026`.
- Only numeric health metadata is stored in
  `nba_research.nba_league_source_probes`: league, provider, sample
  date/year, status, event/identity/final counts, page-completeness flag.
  No names, statistics, scores, injury data, provider content or odds.
  Table RLS is enabled and anon/authenticated roles have no grants.
- Candidate and commercial-authorisation flags remain false.

## Next acceptance gates — no repeated infrastructure rewrites

1. **Rights**: obtain explicit written rights for commercial model inputs,
   derivative outputs, betting-related use and (where needed) score
   redistribution. Public free browsing is NOT enough.
2. **Provenance**: ingest licensed full-season team/game/venue UTC identities
   into a *separate per-league* data namespace. Keep raw and normalized
   source identities, coverage manifests, checksums, and ingestion cursor.
   Never attach non-NBA rows to NBA model training.
3. **Coverage**: independently reconcile each season's every fixture
   to another licensed source; reject missing/pending/identity collisions.
   Check reschedules, playoffs, overtime, NCAA period rules and cross-year
   season naming. Do not treat per-day ESPN event counts as a full season.
4. **Validation**: at least 2 complete seasons and 100 original,
   independently settled forward forecasts **per league**, separate
   score calibration, moneyline Brier and baseline comparisons.
5. **Market settlement**: require bookmaker-specific overtime, push,
   period, injury/DNP, void and player-identity rules; fail closed.
6. **Operations**: schedule licensed production ingestion only after the
   prior gates, with per-league freshness alerts, retries, immutable source
   receipts and independent backups. Do not create a recurring scraper of
   sources without permission.

For EuroLeague content licensing, see the league's official
https://mediacentre.euroleague.net/mediacentre/en/corporateresources .
This free research proof establishes source availability only.
