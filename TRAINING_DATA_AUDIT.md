# BetSightly Training Data Provenance Audit

Generated: `2026-09-27T10:51:48.608388+00:00`

This is a read-only audit. It does not retrain models or rewrite the dataset.

## Executive snapshot

- Raw rows: **66,699**
- Valid finished rows: **66,699**
- Derived trainable samples after the current 5-match warm-up gate: **64,218**
- Dataset date range: **2019-02-22 → 2026-06-01**
- 1X2 complete odds coverage: **99.94%**
- O/U 2.5 complete odds coverage: **58.06%**
- Duplicate fixture keys: **0**
- Conflicting duplicate score keys: **0**
- Cross-country normalized team-name collisions: **0**

## Model-data consistency

- Model metadata samples: **64218**
- Current derived samples: **64,218**
- Current derived split: train **44,952**, calibration **9,633**, test **9,633**
- Train range: **2019-04-05 → 2024-05-15**
- Calibration range: **2024-05-15 → 2025-05-17**
- Test range: **2025-05-17 → 2026-06-01**

## Provenance

- Input path: `C:\Users\ZILLAB\Desktop\betsightly-training-data-audit-20260927\data\api-football\matches.csv`
- SHA-256: `4b66f1e69b8c78eaf2f31daceb6b2ad3279590fedf3095d746114714b8e9b98b`
- Row provenance fields present: `[]`
- Row provenance fields missing: `['source', 'source_url', 'source_file', 'source_row_id', 'odds_source', 'odds_snapshot_type', 'odds_captured_at']`
- Active free fetcher source: **football-data.co.uk**

## Live-vs-training league coverage

- Dataset league IDs: **29**
- Configured API-Football live target IDs: **33**
- Live target IDs missing from training CSV: `[1, 2, 3, 11, 13, 265, 292, 307, 848]`

## Findings

### HIGH — LIVE_LEAGUES_WITHOUT_CURRENT_DATASET_ID

Some API-Football live target leagues have no matching league_id in the current training CSV.

```json
{
  "league_ids": [
    1,
    2,
    3,
    11,
    13,
    265,
    292,
    307,
    848
  ],
  "count": 9
}
```

### HIGH — MISLEADING_SOURCE_PATH

The training CSV path says api-football although the active free fetcher writes football-data.co.uk rows there.

```json
{
  "path": "C:\\Users\\ZILLAB\\Desktop\\betsightly-training-data-audit-20260927\\data\\api-football\\matches.csv",
  "fetcher_source": "football-data.co.uk"
}
```

### HIGH — ODDS_TIMING_SEMANTICS_AMBIGUOUS

Fetcher labels odds as average closing odds but checks AvgH/AvgD/AvgA before AvgCH/AvgCD/AvgCA.

```json
{
  "avg_before_closing": true
}
```

### HIGH — ROW_PROVENANCE_ABSENT

Rows do not carry source/source-file/odds-source/timestamp provenance, so price timing and origin cannot be proven row by row.

```json
{
  "missing_fields": [
    "source",
    "source_url",
    "source_file",
    "source_row_id",
    "odds_source",
    "odds_snapshot_type",
    "odds_captured_at"
  ]
}
```

### MEDIUM — FETCHER_WINDOW_DOC_MISMATCH

Fetcher documentation claims data from 2012, but the configured main-league season window begins later.

```json
{
  "docs_claim": 2012,
  "configured_start": 2019,
  "configured_end": 2025
}
```

### MEDIUM — MARKET_ODDS_NOT_UNIVERSAL

1X2 bookmaker features are missing for part of the corpus; model behavior therefore spans priced and default-filled rows.

```json
{
  "complete_rows": 66661,
  "coverage_pct": 99.943
}
```

### MEDIUM — OU25_ODDS_SPARSE

O/U 2.5 price features are not available across the full corpus.

```json
{
  "complete_rows": 38723,
  "coverage_pct": 58.0563
}
```

### MEDIUM — SPLIT_BOUNDARY_SHARES_CALENDAR_DATE

Row-count splits can place fixtures from one calendar date on both sides of a train/calibration or calibration/test boundary.

```json
{
  "derived_samples": 64218,
  "train": 44952,
  "calib": 9633,
  "test": 9633,
  "train_start": "2019-04-05",
  "train_end": "2024-05-15",
  "calib_start": "2024-05-15",
  "calib_end": "2025-05-17",
  "test_start": "2025-05-17",
  "test_end": "2026-06-01",
  "train_calib_same_date_boundary": true,
  "calib_test_same_date_boundary": true
}
```

### PASS — NO_DIRECT_TARGET_COLUMNS

The current model feature list contains no direct final-score/result columns.

```json
{
  "feature_count": 25,
  "market_feature_count": 6
}
```

## League coverage

| League ID | League | Country | Rows |
|---:|---|---|---:|
| 40 | Championship | England | 3,864 |
| 253 | MLS | USA | 3,507 |
| 128 | Primera Division | Argentina | 3,419 |
| 141 | Segunda Division | Spain | 3,234 |
| 71 | Serie A | Brazil | 2,837 |
| 136 | Serie B | Italy | 2,660 |
| 39 | Premier League | England | 2,660 |
| 135 | Serie A | Italy | 2,660 |
| 140 | La Liga | Spain | 2,660 |
| 203 | Super Lig | Turkey | 2,476 |
| 62 | Ligue 2 | France | 2,410 |
| 98 | J1 League | Japan | 2,372 |
| 61 | Ligue 1 | France | 2,336 |
| 262 | Liga MX | Mexico | 2,317 |
| 283 | Liga I | Romania | 2,181 |
| 78 | Bundesliga | Germany | 2,142 |
| 94 | Primeira Liga | Portugal | 2,142 |
| 79 | 2. Bundesliga | Germany | 2,142 |
| 144 | Pro League | Belgium | 2,085 |
| 88 | Eredivisie | Netherlands | 2,068 |
| 106 | Ekstraklasa | Poland | 2,066 |
| 103 | Eliteserien | Norway | 1,778 |
| 113 | Allsvenskan | Sweden | 1,771 |
| 169 | Super League | China | 1,728 |
| 197 | Super League | Greece | 1,669 |
| 179 | Premiership | Scotland | 1,547 |
| 119 | Superliga | Denmark | 1,399 |
| 218 | Bundesliga | Austria | 1,361 |
| 244 | Veikkausliiga | Finland | 1,208 |

## Recommended next action

Do not retrain yet. First introduce explicit source/odds provenance and a canonical historical identity layer, then rebuild a deduplicated training warehouse and compare its coverage against the SportyBet-first inventory.
