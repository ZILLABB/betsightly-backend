"""Leakage-safe chronological features for shadow model training.

No odds implied by results. Features only use full-time matches from PRIOR
calendar dates, grouped by competition and canonical team identity. Same-day
fixtures are processed as a batch to prevent unknown kickoff order leakage.
This module does not train or replace BetSightly's champion model.
"""
from collections import defaultdict
from datetime import date

MARKETS = ("home_win", "draw", "away_win", "over_1_5", "over_2_5", "btts_yes")


def labels(home_goals: int, away_goals: int) -> dict:
    return {
        "home_win": int(home_goals > away_goals),
        "draw": int(home_goals == away_goals),
        "away_win": int(home_goals < away_goals),
        "over_1_5": int(home_goals + away_goals >= 2),
        "over_2_5": int(home_goals + away_goals >= 3),
        "btts_yes": int(home_goals > 0 and away_goals > 0),
    }


def _team_form(records: list[tuple[int, int]], size: int = 5) -> dict:
    recent = records[-size:]
    if not recent:
        return {"matches": 0, "goals_for": None, "goals_against": None,
                "win_rate": None, "draw_rate": None}
    n = len(recent)
    return {
        "matches": n,
        "goals_for": round(sum(f for f, _ in recent) / n, 4),
        "goals_against": round(sum(a for _, a in recent) / n, 4),
        "win_rate": round(sum(f > a for f, a in recent) / n, 4),
        "draw_rate": round(sum(f == a for f, a in recent) / n, 4),
    }


def build_examples(rows: list[dict], *, min_history: int = 3) -> dict:
    from leagues.sportybet import _norm
    if not 0 <= min_history <= 20:
        raise ValueError("min_history must be between zero and twenty")
    team_history = defaultdict(list)
    # Single fixture record cannot appear twice across imported seasons.
    # Identical dates with conflicting scores are already rejected in parser.
    unique = {}
    for row in rows:
        slug = str(row["league_slug"])
        day = date.fromisoformat(str(row["match_date"]))
        home, away = _norm(row["home_team"]), _norm(row["away_team"])
        if not home or not away or home == away:
            continue
        identity = (slug, day, home, away)
        score = (int(row["home_score"]), int(row["away_score"]))
        if identity in unique and unique[identity][1] != score:
            raise ValueError("Contradictory duplicate match across seasons/sources")
        unique[identity] = (row, score)
    grouped = defaultdict(list)
    for (slug, day, home, away), (row, score) in unique.items():
        grouped[day].append((slug, home, away, row, score))

    examples = []
    skipped = defaultdict(int)
    for day in sorted(grouped):
        batch = sorted(grouped[day], key=lambda x: (
            x[0], x[1], x[2],
        ))
        pending = []
        for slug, home, away, row, (hg, ag) in batch:
            hkey, akey = (slug, home), (slug, away)
            home_records = team_history[hkey]
            away_records = team_history[akey]
            if min(len(home_records), len(away_records)) < min_history:
                skipped["insufficient_prior_team_matches"] += 1
            else:
                examples.append({
                    "fixture_key": row["fixture_key"],
                    "league_slug": slug,
                    "match_date": day.isoformat(),
                    "home_history": _team_form(home_records),
                    "away_history": _team_form(away_records),
                    "home_venue_history": _team_form([
                        x[:2] for x in home_records if x[2] == "home"
                    ]),
                    "away_venue_history": _team_form([
                        x[:2] for x in away_records if x[2] == "away"
                    ]),
                    "labels": labels(hg, ag),
                    "source": row.get("source"),
                    "source_sha256": row.get("source_sha256"),
                })
            pending.append((hkey, (hg, ag, "home")))
            pending.append((akey, (ag, hg, "away")))
        # Only now commit same-day results to history; kickoff order unknown.
        for key, record in pending:
            team_history[key].append(record)
    return {
        "examples": examples,
        "total_deduplicated_results": len(unique),
        "skipped": dict(skipped),
        "feature_policy": "PRIOR_CALENDAR_DAY_ONLY",
        "champion_model_unchanged": True,
        "market_labels": MARKETS,
        "data_quality": "SOURCE_PROVENANCE_ONLY_REQUIRES_INDEPENDENT_VERIFICATION",
    }


def chronological_split(examples: list[dict], train_fraction: float = .8) -> dict:
    if not .5 <= train_fraction <= .9:
        raise ValueError("train_fraction must be between 0.5 and 0.9")
    dates = sorted(set(x["match_date"] for x in examples))
    if len(dates) < 2:
        return {"train": [], "holdout": [], "cutoff_date": None}
    cutoff = dates[min(len(dates) - 1, max(1, int(len(dates) * train_fraction)))]
    return {
        "train": [row for row in examples if row["match_date"] < cutoff],
        "holdout": [row for row in examples if row["match_date"] >= cutoff],
        "cutoff_date": cutoff,
    }
