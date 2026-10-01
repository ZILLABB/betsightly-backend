"""Historical football-result coverage audit for Phase 8A."""
from __future__ import annotations

from collections import Counter
import pandas as pd


def _tier(trainable: int) -> str:
    if trainable >= 1000:
        return "DEEP"
    if trainable >= 500:
        return "ADEQUATE"
    if trainable >= 200:
        return "THIN"
    return "VERY_THIN"


def historical_coverage_report(
    combined: pd.DataFrame,
    features: pd.DataFrame,
    *,
    target_league_ids: set[int] | None = None,
) -> dict:
    source = combined.copy()
    source["date"] = pd.to_datetime(source["date"], errors="coerce")
    source = source.dropna(subset=["date", "league_id"])
    source["league_id"] = source["league_id"].astype(int)

    trainable = features.copy()
    if not trainable.empty:
        trainable["date"] = pd.to_datetime(trainable["date"], errors="coerce")
        trainable["league_id"] = trainable["league_id"].astype(int)

    latest = source["date"].max() if not source.empty else None
    recent_cutoff = (
        latest - pd.Timedelta(days=365)
        if latest is not None else None
    )

    rows = []
    for league_id, group in source.groupby("league_id", sort=True):
        league_features = (
            trainable[trainable["league_id"] == int(league_id)]
            if not trainable.empty else trainable
        )
        names = [
            str(value)
            for value in group["competition"].dropna().tolist()
            if str(value).strip()
        ]
        competition = (
            Counter(names).most_common(1)[0][0]
            if names else f"league-{league_id}"
        )
        min_date = group["date"].min()
        max_date = group["date"].max()
        years = sorted(set(int(v) for v in group["date"].dt.year.tolist()))
        trainable_n = len(league_features)
        rows.append({
            "league_id": int(league_id),
            "competition": competition,
            "results": len(group),
            "trainable": trainable_n,
            "warmup_loss": len(group) - trainable_n,
            "trainable_rate": round(trainable_n / len(group), 6),
            "min_date": min_date.date().isoformat(),
            "max_date": max_date.date().isoformat(),
            "calendar_years": len(years),
            "first_year": years[0] if years else None,
            "last_year": years[-1] if years else None,
            "results_last_365d_of_corpus": (
                int((group["date"] >= recent_cutoff).sum())
                if recent_cutoff is not None else 0
            ),
            "source_counts": dict(Counter(group["source_dataset"].tolist())),
            "coverage_tier": _tier(trainable_n),
        })

    observed = {row["league_id"] for row in rows}
    targets = {int(v) for v in (target_league_ids or set())}

    return {
        "schema": 1,
        "experiment": "phase8_historical_coverage_v1",
        "overview": {
            "unique_results": len(source),
            "trainable_samples": len(trainable),
            "league_count": len(observed),
            "min_date": (
                source["date"].min().date().isoformat()
                if not source.empty else None
            ),
            "max_date": (
                source["date"].max().date().isoformat()
                if not source.empty else None
            ),
            "source_counts": dict(Counter(source["source_dataset"].tolist())),
        },
        "target_league_ids": sorted(targets),
        "target_leagues_present": sorted(targets & observed),
        "target_leagues_missing": sorted(targets - observed),
        "extra_historical_leagues": sorted(observed - targets),
        "thin_or_very_thin": [
            row["league_id"]
            for row in rows
            if row["coverage_tier"] in {"THIN", "VERY_THIN"}
        ],
        "leagues": rows,
    }
