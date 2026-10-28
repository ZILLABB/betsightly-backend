# BetSightly Basketball — permission-gated historical data foundation
Updated 2026-10-28, isolated NBA/basketball staging branch only.

## Actual status

Six source candidates were successfully contacted on 28 October 2026, but
**none is an approved commercial betting-statistics input**. A successful
HTTP 200 or a complete season listing does not convey rights to reproduce
data, train commercial models or provide betting-adjacent services.

The licensed-history foundation consists of three new private PostgreSQL
tables in `nba_research`, a bounded JSONL importer and a read-only
administrator report. Supabase migration was applied with RLS on every table
and no `anon` or `authenticated` grants.

At creation there are ZERO approved grants, ZERO licensed historical games,
and ZERO licensed import receipts. Never confuse the six earlier *source
availability probes* with historical games or source rights.

## What can be imported once rights are approved

- WNBA, NCAA men's and women's, EuroLeague, EuroCup and Australian NBL are
  isolated by league and provider.
- Import only immutable **verified final** game rows (not pregame forecasts,
  scheduled events, voided bets, odds, or unconfirmed period scores).
- A commercially authorized provider must have a separately entered,
  evidence-backed verified grant permitting **storage, model training and
  betting-related use**. Authorizations have an expiry and can be revoked.
- One bounded import is at most 1,000 games and 2.8MB. Larger competitions
  (particularly NCAA D-I) must be split by contiguous, independently
  verified cohorts. The entire season is NOT considered complete because
  a chunk was imported.
- Game event/team IDs, score ranges, non-ties, original UTC tipoffs,
  allowed seasons, hashes and cross-batch immutable identities are enforced.
  Every inserted row SHA is read back in the same transaction.
- A duplicate identical manifest returns `already_imported`; conflicting
  finals fail and leave the previously verified result unchanged.
- Source grants, games and import receipts are **not** included in the
  existing NBA-only V2 Blob backup format. Before real licensed imports are
  operationalized, a separate secure backup/restore acceptance must be
  demonstrated for these three tables.

## Schema and CLI

Migration: `sql/nba_private_licensed_history_20261028.sql` (already
applied to isolated Supabase).

Import only when a genuinely approved grant has been recorded by a database
administrator, following signed-document review. The application's code does
**not** grant rights, and no hard-coded source credential is sufficient.

```sh
python scripts/nba_import_licensed_history.py \
  --league wnba --provider an_authorized_provider \
  --season 2025 --file licensed_wnba_2025.jsonl
```

Example *synthetic* JSONL line for validating the file shape, never a real
provider game:

```json
{"provider_event_id":"synthetic-game-1","tipoff_utc":"2025-11-03T19:00:00+00:00","home_team_id":"fiction-home","away_team_id":"fiction-away","status":"final","home_score":93,"away_score":84}
```

A source identifier or row cannot be generated to "fill" a missing season.
Retain the original provider evidence and signed rights agreement outside
the database; the rights table holds only its SHA-256 fingerprint.

Admin-only status:
`GET /api/growth/admin/nba-research/licensed-history-readiness`.

All imported data remains `research_only`, `not_bookable`, and
`public_publishing_enabled=false`; release decisions are independent.

## Official contacts and rights investigation (no inquiries sent)

| League | Start rights inquiry at | Licensing caveat |
|---|---|---|
| WNBA | NBAS TATS contact on https://stats.wnba.com/help/ (NBASTATS@NBA.com) | Public WNBA statistics terms restrict gambling use |
| NCAA men/women | NCAA research@ncaa.org or ncaastats@ncaa.org (https://www.ncaa.org/news/contact-us/) | Need season-wide D-I data, historical results and commercial/betting-use permission |
| EuroLeague and EuroCup | euroleague@euroleague.net (https://mediacentre.euroleague.net/mediacentre/en/) | Official press reports Sportradar has exclusive official betting data distribution rights through 2031; request clarity before considering another provider |
| Australian NBL | info@nbl.com.au (https://www.nbl.com.au/contact-us) | Ask about official data use, betting-related analysis, redistribution and third-party ESPN source conditions |

Independent public facts about restrictions:
- https://www.wnba.com/terms-of-use
- https://www.nba.com/termsofuse
- https://www.thesportsdb.com/docs_terms_of_use.php (free development access
  does not clear third-party rights; paid-app terms apply)
- https://gdap-portal.fiba.basketball/terms-of-services (authorization required)
- https://mediacentre.euroleague.net/en/app/2/communication/communication/preview/24427
  (official EuroLeague–Sportradar exclusive betting data agreement).

Suggested licensing inquiry scope:

> We are developing BetSightly, a basketball research and probabilistic
> sports-prediction platform. Please confirm whether an agreement may permit
> historical and prospective game identity, schedules, verified final scores,
> team/player statistics, automated collection and storage, commercial model
> training, derivative predictions for a betting-related site, and public
> display of derived results. What are the exact limits, permitted regions,
> sublicensing restrictions, historical coverage, rate limits, fees and
> expiry/revocation rules? We are not seeking video, logos or raw feed
> redistribution unless offered. Do you have a low-cost startup agreement
> or an authorized commercial partner we should contact?

## Future release acceptance (not done by this migration)

1. Receive and verify actual rights documents.
2. Ingest two complete, licensed historical seasons per league.
3. Independently verify provider game identities and final scores; resolve
   reschedules, overtime, doubleheaders, NCAA conference/season mapping.
4. Train each league on pregame-only features with strict chronological
   holdout. Build original pre-tipoff forecasts and accumulate at least
   100 independently settled prospective games per league.
5. Demonstrate approved bookmaker settlement semantics and backup/restore
   of all new licensed-history tables before commercial publication.
