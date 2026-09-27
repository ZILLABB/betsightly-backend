"""Read-only audit of BetSightly's current football training corpus.

This script NEVER rewrites the input CSV and NEVER trains/replaces a model.
It produces a reproducible JSON + Markdown provenance/quality report.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import runpy
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from leagues.chronological_split import describe_whole_date_split

DEFAULT_INPUT = ROOT / "data" / "api-football" / "matches.csv"
DEFAULT_META = ROOT / "models" / "api_football" / "meta.json"
DEFAULT_JSON = ROOT / "audit" / "training_data_audit.json"
DEFAULT_MD = ROOT / "TRAINING_DATA_AUDIT.md"

REQUIRED = [
    "home_team", "away_team", "date", "home_score", "away_score",
    "league_id", "league_name", "country", "league_tier", "season",
]
ODDS_1X2 = ["avg_odds_home", "avg_odds_draw", "avg_odds_away"]
ODDS_OU = ["avg_odds_over25", "avg_odds_under25"]
PROVENANCE_FIELDS = [
    "source", "source_url", "source_file", "source_row_id",
    "odds_source", "odds_snapshot_type", "odds_captured_at",
]
OUTCOME_FIELDS = {
    "home_score", "away_score", "ht_home_score", "ht_away_score",
    "result", "ftr", "fthg", "ftag",
}


def _jsonable(value):
    if value is None:
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _norm_name(value) -> str:
    text = str(value or "").strip().casefold()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _pct(n: int, d: int) -> float:
    return round((n / d * 100.0), 4) if d else 0.0


def _nonempty(series: pd.Series) -> pd.Series:
    return series.notna() & series.astype(str).str.strip().ne("")


def _numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _valid_training_rows(df: pd.DataFrame) -> pd.DataFrame:
    needed = ["date", "home_team", "away_team", "home_score", "away_score"]
    if any(col not in df.columns for col in needed):
        return pd.DataFrame(columns=df.columns)
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce", utc=True)
    out["home_score"] = pd.to_numeric(out["home_score"], errors="coerce")
    out["away_score"] = pd.to_numeric(out["away_score"], errors="coerce")
    out = out.dropna(subset=needed)
    out = out[
        out["home_team"].astype(str).str.strip().ne("")
        & out["away_team"].astype(str).str.strip().ne("")
    ].copy()
    out["home_score"] = out["home_score"].astype(int)
    out["away_score"] = out["away_score"].astype(int)
    return out.sort_values("date").reset_index(drop=True)


def eligible_training_dates(valid: pd.DataFrame) -> list[pd.Timestamp]:
    """Reproduce retrain_models' >=5 prior team-games gate exactly."""
    if valid.empty:
        return []
    team_count: Counter[str] = Counter()
    dates: list[pd.Timestamp] = []

    rows = valid.to_dict("records")
    i = 0
    while i < len(rows):
        day = rows[i]["date"]
        j = i
        day_rows = []
        while j < len(rows) and rows[j]["date"] == day:
            day_rows.append(rows[j])
            j += 1

        for row in day_rows:
            home = row["home_team"]
            away = row["away_team"]
            if team_count[home] >= 5 and team_count[away] >= 5:
                dates.append(pd.Timestamp(day))

        # Same-day outcomes are folded only after every feature row for that
        # date has been assessed, matching the current training code.
        for row in day_rows:
            team_count[row["home_team"]] += 1
            team_count[row["away_team"]] += 1
        i = j
    return dates


def duplicate_summary(valid: pd.DataFrame) -> dict:
    if valid.empty:
        return {
            "duplicate_rows": 0,
            "duplicate_keys": 0,
            "conflicting_score_keys": 0,
            "examples": [],
        }
    work = valid.copy()
    work["_home_n"] = work["home_team"].map(_norm_name)
    work["_away_n"] = work["away_team"].map(_norm_name)
    work["_day"] = work["date"].dt.date.astype(str)
    key = ["_day", "_home_n", "_away_n"]
    sizes = work.groupby(key, dropna=False).size()
    dup_keys = sizes[sizes > 1]
    dup_rows = int(dup_keys.sum()) if len(dup_keys) else 0

    conflicting = []
    for group_key, group in work.groupby(key, dropna=False):
        if len(group) <= 1:
            continue
        scores = set(zip(group["home_score"].astype(int), group["away_score"].astype(int)))
        if len(scores) > 1:
            conflicting.append({
                "date": group_key[0],
                "home": group.iloc[0]["home_team"],
                "away": group.iloc[0]["away_team"],
                "scores": sorted([list(x) for x in scores]),
                "rows": len(group),
            })

    examples = []
    for group_key, count in dup_keys.head(20).items():
        group = work[
            (work["_day"] == group_key[0])
            & (work["_home_n"] == group_key[1])
            & (work["_away_n"] == group_key[2])
        ]
        examples.append({
            "date": group_key[0],
            "home": group.iloc[0]["home_team"],
            "away": group.iloc[0]["away_team"],
            "count": int(count),
            "leagues": sorted(set(group.get("league_name", pd.Series(dtype=str)).dropna().astype(str))),
        })
    return {
        "duplicate_rows": dup_rows,
        "duplicate_keys": int(len(dup_keys)),
        "conflicting_score_keys": int(len(conflicting)),
        "conflicting_examples": conflicting[:20],
        "examples": examples,
    }


def team_country_collisions(df: pd.DataFrame) -> list[dict]:
    if not {"home_team", "away_team", "country"}.issubset(df.columns):
        return []
    rows = []
    for side in ("home", "away"):
        tmp = df[[f"{side}_team", "country"]].copy()
        tmp.columns = ["team", "country"]
        rows.append(tmp)
    teams = pd.concat(rows, ignore_index=True)
    teams["team_norm"] = teams["team"].map(_norm_name)
    teams["country"] = teams["country"].fillna("").astype(str).str.strip()
    teams = teams[(teams["team_norm"] != "") & (teams["country"] != "")]
    grouped = teams.groupby("team_norm")["country"].agg(lambda s: sorted(set(s)))
    out = []
    for team_norm, countries in grouped.items():
        if len(countries) > 1:
            names = teams.loc[teams["team_norm"] == team_norm, "team"].astype(str)
            out.append({
                "normalized_team": team_norm,
                "example_name": names.mode().iat[0] if not names.mode().empty else names.iloc[0],
                "countries": countries,
                "country_count": len(countries),
            })
    out.sort(key=lambda x: (-x["country_count"], x["normalized_team"]))
    return out


def _league_country_name_collisions(df: pd.DataFrame) -> list[dict]:
    if not {"league_name", "country"}.issubset(df.columns):
        return []
    tmp = df[["league_name", "country"]].dropna().copy()
    tmp["league_norm"] = tmp["league_name"].map(_norm_name)
    grouped = tmp.groupby("league_norm")["country"].agg(lambda s: sorted(set(s.astype(str))))
    out = []
    for league_norm, countries in grouped.items():
        if league_norm and len(countries) > 1:
            out.append({
                "normalized_league": league_norm,
                "countries": countries,
                "country_count": len(countries),
            })
    return sorted(out, key=lambda x: (-x["country_count"], x["normalized_league"]))


def _odds_audit(df: pd.DataFrame) -> dict:
    total = len(df)
    result = {}
    for col in ODDS_1X2 + ODDS_OU:
        if col not in df.columns:
            result[col] = {
                "present": False,
                "nonempty": 0,
                "valid_decimal": 0,
                "invalid_nonempty": 0,
                "coverage_pct": 0.0,
            }
            continue
        nonempty = _nonempty(df[col])
        num = _numeric(df[col])
        valid = nonempty & num.gt(1.0)
        result[col] = {
            "present": True,
            "nonempty": int(nonempty.sum()),
            "valid_decimal": int(valid.sum()),
            "invalid_nonempty": int((nonempty & ~num.gt(1.0)).sum()),
            "coverage_pct": _pct(int(valid.sum()), total),
        }

    def complete(cols):
        if any(col not in df.columns for col in cols):
            return 0
        masks = []
        for col in cols:
            num = _numeric(df[col])
            masks.append(_nonempty(df[col]) & num.gt(1.0))
        mask = masks[0]
        for other in masks[1:]:
            mask = mask & other
        return int(mask.sum())

    complete_1x2 = complete(ODDS_1X2)
    complete_ou = complete(ODDS_OU)
    return {
        "columns": result,
        "complete_1x2_rows": complete_1x2,
        "complete_1x2_pct": _pct(complete_1x2, total),
        "complete_ou25_rows": complete_ou,
        "complete_ou25_pct": _pct(complete_ou, total),
    }


def _load_meta(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _fetcher_contract() -> dict:
    path = ROOT / "scripts" / "fetch_history_fdc.py"
    if not path.exists():
        return {"present": False}
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        ns = runpy.run_path(str(path), run_name="training_audit_fetcher")
    except Exception:
        ns = {}
    main_seasons = ns.get("MAIN_SEASONS") or {}
    recent = ns.get("RECENT_SEASONS") or {}
    main_leagues = ns.get("MAIN_LEAGUES") or {}
    extra = ns.get("EXTRA_LEAGUES") or {}
    avg_before_close = (
        text.find('"AvgH", "AvgCH"') >= 0
        or text.find("'AvgH', 'AvgCH'") >= 0
    )
    return {
        "present": True,
        "declared_output": "data/api-football/matches.csv",
        "actual_source": "football-data.co.uk",
        "main_season_start": min(main_seasons.values()) if main_seasons else None,
        "main_season_end": max(main_seasons.values()) if main_seasons else None,
        "configured_main_seasons": dict(main_seasons),
        "configured_recent_seasons": dict(recent),
        "main_league_count": len(main_leagues),
        "extra_league_count": len(extra),
        "docs_claim_2012": "Data from 2012" in text,
        "odds_comment_claims_closing": "historical bookmaker odds (average closing odds)" in text,
        "avg_price_checked_before_avg_closing": bool(avg_before_close),
    }


def _configured_live_leagues() -> set[int]:
    path = ROOT / "services" / "apifootball_service.py"
    if not path.exists():
        return set()
    try:
        ns = runpy.run_path(str(path), run_name="training_audit_api_football")
        return {int(x) for x in (ns.get("TARGET_LEAGUE_IDS") or set())}
    except Exception:
        return set()


def build_audit(input_path: Path, meta_path: Path) -> dict:
    raw = pd.read_csv(input_path, low_memory=False)
    total = len(raw)
    columns = list(raw.columns)
    valid = _valid_training_rows(raw)
    eligible_dates = eligible_training_dates(valid)
    n_samples = len(eligible_dates)

    meta = _load_meta(meta_path)
    feature_columns = list(meta.get("feature_columns") or [])
    direct_outcome_features = sorted(set(feature_columns) & OUTCOME_FIELDS)
    market_features = [f for f in feature_columns if f.startswith("mkt_")]

    split = describe_whole_date_split(
        eligible_dates,
        train_frac=0.70,
        calib_frac=0.15,
    )

    missing = {}
    for col in columns:
        count = int((raw[col].isna() | raw[col].astype(str).str.strip().eq("")).sum())
        missing[col] = {"count": count, "pct": _pct(count, total)}

    date_series = pd.to_datetime(raw.get("date"), errors="coerce", utc=True)
    home_score = pd.to_numeric(raw.get("home_score"), errors="coerce")
    away_score = pd.to_numeric(raw.get("away_score"), errors="coerce")

    duplicate = duplicate_summary(valid)
    team_collisions = team_country_collisions(raw)
    league_name_collisions = _league_country_name_collisions(raw)
    odds = _odds_audit(raw)

    dataset_league_ids = set()
    if "league_id" in raw.columns:
        for value in pd.to_numeric(raw["league_id"], errors="coerce").dropna().astype(int):
            dataset_league_ids.add(int(value))
    live_ids = _configured_live_leagues()

    by_country = []
    if "country" in raw.columns:
        counts = raw["country"].fillna("UNKNOWN").astype(str).value_counts()
        by_country = [{"country": k, "rows": int(v)} for k, v in counts.items()]

    by_league = []
    league_cols = [c for c in ["league_id", "league_name", "country"] if c in raw.columns]
    if league_cols:
        group = raw.groupby(league_cols, dropna=False).size().sort_values(ascending=False)
        for key, count in group.items():
            if not isinstance(key, tuple):
                key = (key,)
            row = {league_cols[i]: _jsonable(key[i]) for i in range(len(league_cols))}
            row["rows"] = int(count)
            by_league.append(row)

    by_season = []
    if "season" in raw.columns:
        counts = raw["season"].fillna("UNKNOWN").astype(str).value_counts().sort_index()
        by_season = [{"season": k, "rows": int(v)} for k, v in counts.items()]

    provenance_present = [f for f in PROVENANCE_FIELDS if f in columns]
    provenance_missing = [f for f in PROVENANCE_FIELDS if f not in columns]

    fetcher = _fetcher_contract()
    findings = []

    def finding(severity, code, message, evidence):
        findings.append({
            "severity": severity,
            "code": code,
            "message": message,
            "evidence": evidence,
        })

    if "api-football" in str(input_path).replace("\\", "/").casefold() and fetcher.get("actual_source") == "football-data.co.uk":
        finding(
            "HIGH", "MISLEADING_SOURCE_PATH",
            "The training CSV path says api-football although the active free fetcher writes football-data.co.uk rows there.",
            {"path": str(input_path), "fetcher_source": fetcher.get("actual_source")},
        )
    if not provenance_present:
        finding(
            "HIGH", "ROW_PROVENANCE_ABSENT",
            "Rows do not carry source/source-file/odds-source/timestamp provenance, so price timing and origin cannot be proven row by row.",
            {"missing_fields": provenance_missing},
        )
    if fetcher.get("odds_comment_claims_closing") and fetcher.get("avg_price_checked_before_avg_closing"):
        finding(
            "HIGH", "ODDS_TIMING_SEMANTICS_AMBIGUOUS",
            "Fetcher labels odds as average closing odds but checks AvgH/AvgD/AvgA before AvgCH/AvgCD/AvgCA.",
            {"avg_before_closing": True},
        )
    if fetcher.get("docs_claim_2012") and (fetcher.get("main_season_start") or 9999) > 2012:
        finding(
            "MEDIUM", "FETCHER_WINDOW_DOC_MISMATCH",
            "Fetcher documentation claims data from 2012, but the configured main-league season window begins later.",
            {
                "docs_claim": 2012,
                "configured_start": fetcher.get("main_season_start"),
                "configured_end": fetcher.get("main_season_end"),
            },
        )
    if duplicate["conflicting_score_keys"]:
        finding(
            "HIGH", "CONFLICTING_DUPLICATE_RESULTS",
            "At least one same-date/team fixture key has conflicting final scores.",
            {"count": duplicate["conflicting_score_keys"]},
        )
    elif duplicate["duplicate_keys"]:
        finding(
            "MEDIUM", "DUPLICATE_FIXTURE_KEYS",
            "Duplicate same-date/home/away fixture keys exist and should be deterministically deduplicated before training.",
            {"keys": duplicate["duplicate_keys"], "rows": duplicate["duplicate_rows"]},
        )
    if team_collisions:
        finding(
            "HIGH", "TEAM_NAME_CROSS_COUNTRY_COLLISIONS",
            "Training history is keyed by raw team name, so identical normalized names in multiple countries can contaminate rolling form/H2H identity.",
            {"collision_count": len(team_collisions), "examples": team_collisions[:10]},
        )
    if split["train_calib_same_date_boundary"] or split["calib_test_same_date_boundary"]:
        finding(
            "MEDIUM", "SPLIT_BOUNDARY_SHARES_CALENDAR_DATE",
            "Row-count splits can place fixtures from one calendar date on both sides of a train/calibration or calibration/test boundary.",
            split,
        )
    if direct_outcome_features:
        finding(
            "BLOCKER", "DIRECT_TARGET_LEAKAGE",
            "Outcome/result columns appear directly in the model feature list.",
            {"features": direct_outcome_features},
        )
    else:
        finding(
            "PASS", "NO_DIRECT_TARGET_COLUMNS",
            "The current model feature list contains no direct final-score/result columns.",
            {"feature_count": len(feature_columns), "market_feature_count": len(market_features)},
        )

    meta_samples = meta.get("n_samples")
    if meta_samples is not None and int(meta_samples) != n_samples:
        finding(
            "MEDIUM", "MODEL_DATASET_DRIFT",
            "The current CSV-derived trainable sample count differs from the sample count recorded by the deployed model metadata.",
            {"meta_samples": int(meta_samples), "current_derived_samples": n_samples},
        )
    if live_ids:
        missing_live = sorted(live_ids - dataset_league_ids)
        if missing_live:
            finding(
                "HIGH", "LIVE_LEAGUES_WITHOUT_CURRENT_DATASET_ID",
                "Some API-Football live target leagues have no matching league_id in the current training CSV.",
                {"league_ids": missing_live, "count": len(missing_live)},
            )

    if odds["complete_1x2_rows"] < total:
        finding(
            "MEDIUM", "MARKET_ODDS_NOT_UNIVERSAL",
            "1X2 bookmaker features are missing for part of the corpus; model behavior therefore spans priced and default-filled rows.",
            {
                "complete_rows": odds["complete_1x2_rows"],
                "coverage_pct": odds["complete_1x2_pct"],
            },
        )
    if odds["complete_ou25_rows"] < total:
        finding(
            "MEDIUM", "OU25_ODDS_SPARSE",
            "O/U 2.5 price features are not available across the full corpus.",
            {
                "complete_rows": odds["complete_ou25_rows"],
                "coverage_pct": odds["complete_ou25_pct"],
            },
        )

    report = {
        "schema": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "input": {
            "path": str(input_path),
            "size_bytes": input_path.stat().st_size,
            "sha256": _sha256(input_path),
        },
        "rows": {
            "raw": total,
            "valid_finished": len(valid),
            "invalid_training_rows": total - len(valid),
            "derived_trainable_samples_after_5_game_warmup": n_samples,
        },
        "date_range": {
            "min": date_series.min().date().isoformat() if date_series.notna().any() else None,
            "max": date_series.max().date().isoformat() if date_series.notna().any() else None,
            "invalid_dates": int(date_series.isna().sum()),
        },
        "scores": {
            "invalid_home": int(home_score.isna().sum()),
            "invalid_away": int(away_score.isna().sum()),
            "negative_rows": int(((home_score < 0) | (away_score < 0)).fillna(False).sum()),
            "extreme_gt_15_rows": int(((home_score > 15) | (away_score > 15)).fillna(False).sum()),
        },
        "columns": columns,
        "missingness": missing,
        "odds": odds,
        "duplicates": duplicate,
        "team_country_collisions": team_collisions,
        "league_name_country_collisions": league_name_collisions,
        "coverage": {
            "countries": by_country,
            "leagues": by_league,
            "seasons": by_season,
            "dataset_league_ids": sorted(dataset_league_ids),
            "configured_live_api_football_league_ids": sorted(live_ids),
            "configured_live_ids_missing_from_dataset": sorted(live_ids - dataset_league_ids),
            "dataset_ids_not_in_live_target_registry": sorted(dataset_league_ids - live_ids),
        },
        "provenance": {
            "present_fields": provenance_present,
            "missing_fields": provenance_missing,
            "fetcher_contract": fetcher,
        },
        "training_contract": {
            "model_meta_path": str(meta_path),
            "model_trained_at": meta.get("trained_at"),
            "meta_n_samples": meta_samples,
            "meta_split": meta.get("split"),
            "feature_columns": feature_columns,
            "market_feature_columns": market_features,
            "direct_outcome_columns_in_features": direct_outcome_features,
            "derived_split": split,
            "supported_team_types_declared": meta.get("supported_team_types"),
        },
        "findings": findings,
    }
    return report


def render_markdown(report: dict) -> str:
    rows = report["rows"]
    odds = report["odds"]
    split = report["training_contract"]["derived_split"]
    coverage = report["coverage"]
    prov = report["provenance"]
    findings = report["findings"]

    lines = [
        "# BetSightly Training Data Provenance Audit",
        "",
        f"Generated: `{report['generated_at']}`",
        "",
        "This is a read-only audit. It does not retrain models or rewrite the dataset.",
        "",
        "## Executive snapshot",
        "",
        f"- Raw rows: **{rows['raw']:,}**",
        f"- Valid finished rows: **{rows['valid_finished']:,}**",
        f"- Derived trainable samples after the current 5-match warm-up gate: **{rows['derived_trainable_samples_after_5_game_warmup']:,}**",
        f"- Dataset date range: **{report['date_range']['min']} → {report['date_range']['max']}**",
        f"- 1X2 complete odds coverage: **{odds['complete_1x2_pct']:.2f}%**",
        f"- O/U 2.5 complete odds coverage: **{odds['complete_ou25_pct']:.2f}%**",
        f"- Duplicate fixture keys: **{report['duplicates']['duplicate_keys']:,}**",
        f"- Conflicting duplicate score keys: **{report['duplicates']['conflicting_score_keys']:,}**",
        f"- Cross-country normalized team-name collisions: **{len(report['team_country_collisions']):,}**",
        "",
        "## Model-data consistency",
        "",
        f"- Model metadata samples: **{report['training_contract']['meta_n_samples']}**",
        f"- Current derived samples: **{split['derived_samples']:,}**",
        f"- Current derived split: train **{split['train']:,}**, calibration **{split['calib']:,}**, test **{split['test']:,}**",
        f"- Train range: **{split['train_start']} → {split['train_end']}**",
        f"- Calibration range: **{split['calib_start']} → {split['calib_end']}**",
        f"- Test range: **{split['test_start']} → {split['test_end']}**",
        "",
        "## Provenance",
        "",
        f"- Input path: `{report['input']['path']}`",
        f"- SHA-256: `{report['input']['sha256']}`",
        f"- Row provenance fields present: `{prov['present_fields']}`",
        f"- Row provenance fields missing: `{prov['missing_fields']}`",
        f"- Active free fetcher source: **{prov['fetcher_contract'].get('actual_source')}**",
        "",
        "## Live-vs-training league coverage",
        "",
        f"- Dataset league IDs: **{len(coverage['dataset_league_ids'])}**",
        f"- Configured API-Football live target IDs: **{len(coverage['configured_live_api_football_league_ids'])}**",
        f"- Live target IDs missing from training CSV: `{coverage['configured_live_ids_missing_from_dataset']}`",
        "",
        "## Findings",
        "",
    ]
    order = {"BLOCKER": 0, "HIGH": 1, "MEDIUM": 2, "PASS": 3}
    for item in sorted(findings, key=lambda x: (order.get(x["severity"], 9), x["code"])):
        lines.append(f"### {item['severity']} — {item['code']}")
        lines.append("")
        lines.append(item["message"])
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(item["evidence"], indent=2, default=_jsonable))
        lines.append("```")
        lines.append("")

    lines += [
        "## League coverage",
        "",
        "| League ID | League | Country | Rows |",
        "|---:|---|---|---:|",
    ]
    for row in coverage["leagues"]:
        lines.append(
            f"| {row.get('league_id', '')} | {row.get('league_name', '')} | "
            f"{row.get('country', '')} | {row['rows']:,} |"
        )

    lines += [
        "",
        "## Recommended next action",
        "",
        "Do not retrain yet. First introduce explicit source/odds provenance and a canonical historical identity layer, then rebuild a deduplicated training warehouse and compare its coverage against the SportyBet-first inventory.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--meta", type=Path, default=DEFAULT_META)
    parser.add_argument("--json-out", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--md-out", type=Path, default=DEFAULT_MD)
    args = parser.parse_args()

    input_path = args.input.resolve()
    if not input_path.exists():
        raise SystemExit(f"Training CSV not found: {input_path}")

    report = build_audit(input_path, args.meta.resolve())

    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(
        json.dumps(report, indent=2, default=_jsonable),
        encoding="utf-8",
    )
    args.md_out.write_text(render_markdown(report), encoding="utf-8")

    severities = Counter(item["severity"] for item in report["findings"])
    print("\nTRAINING DATA AUDIT COMPLETE")
    print(f"input: {input_path}")
    print(f"raw rows: {report['rows']['raw']:,}")
    print(f"valid finished: {report['rows']['valid_finished']:,}")
    print(
        "derived trainable: "
        f"{report['rows']['derived_trainable_samples_after_5_game_warmup']:,}"
    )
    print(
        "model meta samples: "
        f"{report['training_contract']['meta_n_samples']}"
    )
    print(
        f"1X2 odds coverage: {report['odds']['complete_1x2_pct']:.2f}% | "
        f"O/U 2.5: {report['odds']['complete_ou25_pct']:.2f}%"
    )
    print(
        "duplicates: "
        f"{report['duplicates']['duplicate_keys']} keys / "
        f"{report['duplicates']['conflicting_score_keys']} conflicting"
    )
    print(
        "team-country collisions: "
        f"{len(report['team_country_collisions'])}"
    )
    print(
        "live target league IDs missing from dataset: "
        f"{report['coverage']['configured_live_ids_missing_from_dataset']}"
    )
    print(
        "findings: "
        + ", ".join(f"{k}={v}" for k, v in sorted(severities.items()))
    )
    print(f"json: {args.json_out}")
    print(f"markdown: {args.md_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
