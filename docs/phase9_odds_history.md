# Phase 9: odds evidence and CLV (shadow-only)

This warehouse is not read by the predictor, Builder optimizer, publication,
booking validator, or settlement engine. The migration `add_odds_history_clv`
follows `add_prepared_board_cache`. Both tables are append-only (database
triggers reject updates and deletes). Source/leg and snapshot identities make
retry insertion idempotent.

## Capture ownership and quota

`ODDS_HISTORY_CAPTURE_ENABLED=false` by default. Apply the migration before
setting it to `true`. Enable it on the single background board owner to record
provider snapshots and on web only if interactive Builder entry-price records
are desired. Web entry recording is a small database insert, not a fetch. The seven-day
pipeline records exact-matched SportyBet prices from the board it already
fetched. The budgeted odds-shop path records raw The Odds API h2h quotes only
when that existing path actually fetches them; those quotes are marked **not
exact-bookable** and cannot establish closing odds under the current policy.
Neither hook makes an additional provider request. Public CLV GET endpoints
are API-key protected and read only.

Builder V2 and official published slip archives link per-leg real entry prices
to their immutable source identity. A validated SportyBet code establishes
that the selection set passed readback, but existing responses do not include
authenticated **per-leg** readback prices; the warehouse labels those prices
`validated_booking_board_quote`, not `readback_price`. Estimated/model prices
are skipped. Past records remain unchanged.

An evaluable closing quote must share exact canonical fixture identity or a
stored provider event ID, market, selection and kickoff. It must be real,
bookable, later than entry, and earlier than kickoff minus the 60-second safety
window. Before that window passes the result is pending. If no qualifying
quote exists afterward it is unavailable, never interpolated. Formulas:

- `price_clv = entry_odds / closing_odds - 1`
- `probability_clv = 1 / closing_odds - 1 / entry_odds`

Reports show selection, evaluated, pending and unavailable counts overall and
per market, league, mode, horizon, policy version and entry source. These are
descriptive; small samples do not establish model skill. The Odds API rows
cannot be used as SportyBet closing prices without a later verified mapping
and bookability policy. An optional `capture_closing_snapshot()` helper uses
the existing SportyBet client and a PostgreSQL advisory lease. It has no
registered schedule and refuses to fetch unless
`ODDS_HISTORY_CLOSE_FETCH_ENABLED=true` on a `worker`/`scheduler` role. It is
disabled by default; frequency and network cost require separate operational
approval. It never calls The Odds API.

## Staging validation (not run on production here)

1. Back up staging PostgreSQL, then run `python -m alembic upgrade head`.
2. Set `ODDS_HISTORY_CAPTURE_ENABLED=true` on the single background owner
   after migration. Enable it on web to record Builder entry prices; web does
   not use this flag to fetch odds. Keep existing Odds API quota settings unchanged.
3. Run the normal staging seven-day board job once. Verify new observation
   rows and stable counts on a retry, with no new provider call path.
4. Build a staging V2 ticket and publish a staging daily card; verify linked
   entry rows identify the source and no model odds are labeled real.
5. Request authenticated `GET /api/leagues/clv/status` and
   `GET /api/leagues/clv/report?start=2026-10-02&end=2026-10-09`.
6. After a fixture's kickoff, verify a qualifying later pre-kickoff snapshot
   completes CLV; no later snapshot means unavailable.

Read-only bounded backfill preview (date range at most 31 days):

`python -m scripts.backfill_odds_entry_prices --start 2026-10-02 --end 2026-10-09`

After reviewing the preview, staging-only apply:

`python -m scripts.backfill_odds_entry_prices --start 2026-10-02 --end 2026-10-09 --apply --confirm BACKFILL_ARCHIVE_ENTRY_PRICES`

Backfill creates **entry** rows only from stored real odds. It never creates
historical closing observations. No staging or production backfill was run as
part of this implementation.
