# Jev External Evidence — Batch 2 provider pilot (2026-10-28)

Master implementation tracker: [#240](https://github.com/ZILLABB/betsightly-backend/issues/240)

## Source decisions and actual limitations

| Source | Data | Free access | Production decision | Evidence limitations |
|---|---|---|---|---|
| Existing ESPN | Fixtures, records, provider prices | Already integrated in BetSightly | Reuse existing pipeline | Not an independent Jev news opinion; retain data age and source |
| Existing SportyBet board | Bookmaker mapping, live prices and exact share-code readback | Already integrated | Reuse gated access | Never interpret price as proof of an outcome |
| **OpenLigaDB** | German football match fixtures and community-entered historical finals | HTTPS JSON, keyless, published 60 requests/IP/min limit | **Implemented optional read-only pilot** for \`bl1\`, \`bl2\`, \`bl3\` | ODbL attribution; community-provided results not automatic verified finals; no trustworthy injury/lineup feeds |
| TheSportsDB public v1 | Limited free sports API | Published free key \`123\`, 30 requests/min, method and volume restrictions | **Not enabled for commercial/production polling** pending terms/entitlement review | Official terms: do not scrape the website; free tier useful for development, published appstore apps require paid tier |
| Official club/news feeds | Injuries, confirmed lineups, suspensions, press releases | Varies by club | **Not enabled** until each feed's permitted terms, team identity and timestamp can be proven | Unsubstantiated media rumors must not be treated as official news |

Provider documentation and licensing:
- https://api.openligadb.de/index.html (pinned keyless endpoints; change-date polling and 60 requests/min published)
- https://www.openligadb.de/ (ODbL and community attribution)
- https://www.thesportsdb.com/documentation (free v1 method restrictions, 30 requests/min)
- https://www.thesportsdb.com/docs_terms_of_use.php (free-use and no website scraping terms)

## Delivered source pilot

\`leagues/external_openligadb.py\` is **disabled by default**. Only explicit Python callers can fetch one matchday at a time with \`BETSIGHTLY_EXTERNAL_FOOTBALL_ENABLED=true\`. It is not wired into daily publication, model inference, results checker, or a public endpoint, and has no automatic scheduler.

The adapter:
- uses a fixed HTTPS API host and three explicit league shortcuts; rejects invalid seasons/matchdays and disallows redirects;
- bounds each request to 8 seconds and 512 KB, performs one call per miss and caches successful matchdays for 30 minutes in the process;
- distinguishes halftime vs full-time by \`resultTypeID == 2\` and \`matchIsFinished\`, never substitutes halftime/missing values;
- emits only the source's own fixture ID, source URL, observation timestamp, normalized team/league fields, and community-reported result, preserving ODbL attribution;
- never calls the score settlement engine or marks a bookable pick as verified, even if it reads a community-provided final;
- rejects forged historical replay using a capture timestamp later than the requested \`as_of\`.

**Important:** Source fixture IDs are NOT automatically equivalent to ESPN or SportyBet match IDs. Before any external evidence is shown to Jev for a specific prediction, Batch 3 must use independent, tested event/team/kickoff/competition matching and reject ambiguous mappings. Unit tests that illustrate the evidence envelope do not imply mapping works.

## Next acceptance gates

1. Confirm an actual OpenLigaDB request through an authorized backend staging worker and measure response/coverage; mocks alone are insufficient.
2. Build vetted official club/league feeds for injuries, suspensions and lineups only after reviewing their reuse permissions; keep source-level reliability categories.
3. Cross-provider match identity and data-freshness validation with ambiguous-match quarantine (Batch 3).
4. Persist and version captured evidence snapshots for genuine before-kickoff comparisons, with stale-data alerting.
5. Implement optional cloud-scheduled external fetches separately from daily publishing. If a source fails, no change to stored predictions, bookmaker codes, or settlement.
6. Jev API usage remains disabled until an authorized backend key, quota and spend cap are confirmed; use shadow mode only.

**Current batch status:** one API adapter and offline regression tests, **not** the complete multi-source injury/news intelligence layer. Do not mark Batch 2 closed until production source-policy and fixture identity checks pass.
