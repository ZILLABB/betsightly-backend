# BetSightly Basketball

**Basketball is disabled in production and not ready for wagering.**

The original basketball data fetcher, feature engineering, XGBoost / LightGBM
models and prediction service in this directory are historical prototypes.
Earlier versions used **randomized statistics and generated sample games**,
then made unvalidated performance claims. The legacy training and prediction
entrypoints are intentionally blocked until fully replaced. Do not use
`setup_basketball.py`, `train_models.py` or `predict_games.py`
for production research, selection or publishing.

The maintained private, no-cost NBA development pipeline is documented in
[RESEARCH.md](RESEARCH.md). It performs free historical game ingestion,
deterministic point-in-time feature engineering, chronological moneyline
backtesting and private non-bookable paper forecasting.

No basketball endpoints are mounted in the active FastAPI router.
No public release, bookmaker integration or automation is authorized.
