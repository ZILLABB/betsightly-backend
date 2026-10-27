# BetSightly Basketball — A–D evidence and markets expansion (27 Oct 2026)

## Scope and boundaries

- **NBA:** approved experimental private prospective research; bookmaker booking is a
  *different* service/ledger from model scoring.
- **WNBA / NCAA men / NCAA women:** ESPN candidate adapters in
  `research_other_league_sources.py`. No model training, publication,
  third-party bookmaker grade or cross-league confidence leakage.
- **EuroLeague / EuroCup:** publicly documented official competition feeds:
  `https://api-live.euroleague.net/v2/competitions/E/seasons/E2026/games`
  and the equivalent `U` competition; historical player/team stats
  available through v3. These are **not imported or source-verified by
  BetSightly yet**. Must audit schemas, authorization, license, pagination,
  2026–27 date coverage, missing finals and club aliases before implementation.
- **Australia NBL:** official public schedule/results at
  `https://schedule.nbl.com.au/nbl`. No validated ingestion.
- **SportyBet:** international basketball board offers additional teams and
  leagues, but odds availability is not a trained prediction dataset. A
  bookmaker-only competition must remain absent from public NBA model grades.

## Four-batch acceptance matrix

| Batch | Shipped source/control | Must be proved before production |
| --- | --- | --- |
| A | Existing NBA research settlement/forecast/market OIDC; private NBA ticket ledger scheduler PR #187 | Unattended runs for two NBA match days, ledger wins/losses/void, provider outage retries, restore drill |
| B | Default-disabled, exact bookmaker market probes for 223 spread, 227/228 team totals (PR #187) | Verified actual outcome IDs/descriptions, point-line sign, bookmaker readback, NBA overtime rule, no ambiguous market or phantom code |
| C | Research model-readiness registry and candidate source normalizers | Prior-season data, original timestamps, injury/player identity, pace/possession/margin and point-error baselines, calibration and no train/test leakage |
| D | WNBA/NCAA score candidate inspection; EuroLeague/EuroCup/NBL evaluated as next | League score agreement, nicknames and season identities, league periods, postponements, never NBA-specific model leakage |

## Market roadmap and score requirements

1. **Full-game moneyline/totals:** Already supported for exact active sportsbook
   values, overtime included. NBA ESPN final must uniquely match home/away,
   tipoff and full-time completion.
2. **Full-game spreads / alternate totals / home-away team points:** source
   identity and exact side-specific result units must be verified; guarded
   catalogue currently **off**.
3. **Halves / quarters:** separate period score ingestion and matching official
   market period rules. NCAA men have 20-minute halves; WNBA, EuroLeague and
   women's NCAA use 10-minute quarters. Never apply full-game or overtime scores
   to regulation-only markets.
4. **Player points/rebounds/assists/three-pointers:** verified immutable player
   IDs, roster/team mapping, official minutes, original injury availability,
   DNP/void rules, event boxscores, bookmaker prop identity and independent
   calibration. No player prop selection while any is missing.
5. **Other leagues:** never label a league model-ready merely because it
   appears in the bookmaker's live tournament filters.

## No unsupported promises

A green CI run demonstrates syntax and offline contract tests, **not** a
validated betting edge, available odds, risk-free booking, settlement SLA or
live score provider availability. Public predictions stay excluded pending
independent pregame evidence and meaningful forward validation.

The future migrations must preserve immutable original NBA records and import
additional leagues under new namespaces. Free NBA staging Postgres has a
declared expiry of 24 November 2026; prioritize offsite verified backup and
isolated restore before migration.
