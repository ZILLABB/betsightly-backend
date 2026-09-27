\
# BetSightly Football History Ingestion

This phase creates a separate **results-only** historical dataset for football
form, Elo, replay and future challenger-model work.

It does **not** modify the deployed 25-feature ensemble and does **not** treat
results-only OpenFootball rows as market-training rows.

## Verified OpenFootball coverage

The ingestion supports:

- API-Football league 1 — FIFA World Cup
- API-Football league 2 — UEFA Champions League
- API-Football league 3 — UEFA Europa League
- API-Football league 11 — Copa Sudamericana
- API-Football league 13 — Copa Libertadores
- API-Football league 848 — UEFA Conference League

The previous source registry incorrectly left Copa Sudamericana unresolved.
OpenFootball's `south-america/copa-libertadores/*_copas.txt` files are explicitly
titled `Copa Sudamericana`, so league 11 is now a verified results-history source.

## Safety / provenance contract

Every normalized row carries:

- provider
- repository
- pinned source commit
- source file
- pinned raw URL
- source-file SHA-256
- deterministic source-row ID
- league ID / competition / season

No bookmaker prices are inferred.

Rows whose score notation uses penalties or extra time are excluded in this
first ingestion version because those files mix 90-minute, extra-time and
shootout score semantics. This is intentionally fail-closed.

## Build locally

```powershell
python scripts/build_football_history.py
```

Optional historical window:

```powershell
python scripts/build_football_history.py --min-year 2012 --max-year 2026
```

Outputs are written under:

- `data/football_history/openfootball_matches.csv`
- `data/football_history/manifest.json`

These outputs are for audit and challenger-data preparation. Do not merge them
into the deployed market training CSV.

## Parser hardening

The ingestion now supports the historical World Cup score layouts used by
OpenFootball, including UTC-offset prefixes and trailing venue annotations.

Single-year competitions are pinned to their source year, so section ordering
cannot fabricate a following year. Historical output is also cut off at the
last fully completed UTC calendar day, preventing future-dated source rows from
entering training or replay data.
