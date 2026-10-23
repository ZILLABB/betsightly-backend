# NBA real-data baseline — 23 October 2026 (UTC)

**Status:** research-only; valid historical test, **not** live profitable
performance, and **not** a booking recommendation.

## Reproducible provenance

- Source: SportsDataverse release `espn_nba_schedules` (ESPN-derived NBA schedules and scores), accessed without an API key.
- Downloaded release assets: `nba_schedule_2017.csv` through `nba_schedule_2027.csv`.
- Code branch: `research/nba-offline-pipeline-20261023`.
- Verified workflow: [NBA Historical Research Backtest — run #40029507617](https://github.com/ZILLABB/betsightly-backend/actions/runs/40029507617).
- Source SHA256 checksums and coverage/metric JSON uploaded to the run as a
  short-lived summary artifact. No raw provider data, model pickle or paper
  forecast was uploaded.
- Dataset total: **13,258** distinct regular-season fixture records (2017–2027).
- Completed: **12,016** regular-season results.
- Eligible supervised pregame feature rows: **11,192**, with >=5 previously
  completed same-season games for both teams.
- Source quality: 2027 schedule had **6** unidentifiable regular-season rows;
  they were excluded, counted and did not exceed the 1% rejection budget.

### Chronological evaluation (no random train/test shuffling)

| Window | Calendar dates | Games |
|---|---|---:|
| Training | through 2023-11-10 | 7,784 |
| Validation | 2023-11-11 – 2025-01-25 | 1,697 |
| Untouched historical test | 2025-01-26 – 2026-04-12 | 1,711 |

Hyperparameter `C=1.0` selected using validation Brier score only.

| Metric | Validation | Untouched test | Constant home-win baseline (test) |
|---|---:|---:|---:|
| Accuracy | 64.231% | **65.926%** | 54.880% |
| Brier (lower better) | 0.21739 | **0.21347** | 0.24804 |
| Log loss (lower better) | 0.62345 | **0.61516** | 0.68923 |

After freezing the historical test report, the model was refit on all 11,192
eligible completed games (up to 2026-04-12) for *future* paper predictions.
The refitted prospective model was not used to re-score the historical test.

## What this evidence does **not** show

- It does not establish expected betting return, moneyline market value,
  vig-adjusted probabilities or SportyBet pricing accuracy; this dataset has
  **no timestamped bookmaker odds**.
- It does not incorporate current confirmed injuries, lineups, travel distance,
  historical closing lines or player-level pregame advanced stats.
- The baseline model requires five genuine **same-season** prior games per
  team; at the snapshot timestamp, the 2026–27 schedule yielded **zero
  eligible upcoming paper fixtures**. Zero is reported honestly: no predictions
  were generated or substituted.
- Rights to access a public downloadable file must not be conflated with a
  commercial data license. Research is segregated until source rights are
  confirmed.

## Next independent gates

1. Reproduce an identical data snapshot by SHA256 and rerun the same test.
2. Start **prospective** immutable paper archives only when upcoming fixtures
   genuinely qualify, generated before tipoff.
3. Verify final scores and append-only record scoring over a meaningful sample.
4. Compare against timestamped bookmaker prices, market baselines and a
   pre-registered no-bet threshold before discussing bookmaker integration.
5. Keep basketball routes disabled, all betting codes null, and no public picks.

### Offline commands

```bash
python -m basketball.research_cli fetch-public --seasons 2017 2018 2019 2020 2021 2022 2023 2024 2025 2026 2027
python -m basketball.research_cli report
python -m basketball.research_cli train
# A paper command must be run locally before actual tipoff and after both teams
# have five prior completed games in the same season:
python -m basketball.research_cli paper --date 2026-11-05
```

The final paper command above is **an example**, not a claim that fixtures
will qualify on that date. Empty results are expected whenever gates fail.
