"""NBA score advance: 2024 train, 2025 model choice, 2026 retrospective."""
from copy import deepcopy
from datetime import date, timedelta

import pytest

from basketball.research_cli import build_parser
from basketball.research_advanced_features import FEATURE_COLUMNS
from basketball.research_advanced_score_compare import (
    MODEL, compare_rows, _interval, _validated_rows,
)


def synthetic(*, train=230, tune=120, test=115):
    output=[]
    for season,count in ((2024,train),(2025,tune),(2026,test)):
        start=date(season-1,11,1)
        for index in range(count):
            f = [round(
                float((i % 7)*.37 + (index % 17)*.13 +
                      ((i*index) % 23)*.007 + (season-2024)*.25),
                5) for i in range(len(FEATURE_COLUMNS))]
            delta=(f[16]-f[17])*4+(index%9)*.5
            total=218+(f[14]+f[15])*1.1+delta+((index*13)%11)
            margin=6+(f[18]-f[19])*3+((index*11)%7)
            row={
                "game_id": str(season*10000+index),
                "date": (start+timedelta(days=index//8)).isoformat(),
                "season": season, "status":"final",
                "features": tuple(f),
                "total_points": total,
                "home_margin": margin,
            }
            output.append(row)
    return output


def test_real_advanced_vs_matched_basic_with_no_train_eval_leakage():
    input_rows=synthetic()
    backup=deepcopy(input_rows)
    result=compare_rows(input_rows)
    assert result["status"]=="retrospective_diagnostic_only"
    assert result["version"]==MODEL
    assert result["cohorts"]=={"train":230,"tune":120,"test":115}
    assert result["model_promoted"] is False
    assert result["verified_pregame_2027_settlements"]==0
    for target in ("total_points","home_margin"):
        measurements=result["analysis"][target]
        assert measurements["advanced"]["games"]==115
        assert measurements["matched_basic"]["games"]==115
        assert measurements["uncertainty"]["independent_days"]>=6
        assert set(measurements["train_tune_configuration"])=={
            "basic_previous_games","advanced_pace_and_efficiency"}
    assert input_rows == backup
    assert result["no_writes"] is True


def test_changing_2026_scores_does_not_change_2025_tuned_parameters():
    original=synthetic()
    mutated=deepcopy(original)
    for row in mutated:
        if row["season"]==2026:
            row["total_points"]+=40
            row["home_margin"]-=18
    one=compare_rows(original)
    two=compare_rows(mutated)
    for target in ("total_points","home_margin"):
        assert one["analysis"][target]["train_tune_configuration"]==(
            two["analysis"][target]["train_tune_configuration"])
    assert one["cohorts"]==two["cohorts"]


def test_missing_data_fails_closed_without_false_model_success():
    result=compare_rows(synthetic(test=30))
    assert result["status"]=="blocked"
    assert result["reason"]=="insufficient_exact_advanced_boxscore_cohorts"
    assert result["model_promoted"] is False


def test_invalid_features_labels_duplicate_games_are_blocked():
    rows=synthetic()
    corrupt=deepcopy(rows)
    corrupt[2]["features"]=(float("nan"),)+corrupt[2]["features"][1:]
    with pytest.raises(ValueError,match="nonfinite"):
        compare_rows(corrupt)
    corrupt=deepcopy(rows)
    corrupt[9]["total_points"]=None
    with pytest.raises(ValueError,match="scoring label"):
        compare_rows(corrupt)
    corrupt=deepcopy(rows)
    corrupt.append(deepcopy(corrupt[0]))
    with pytest.raises(ValueError,match="Duplicate"):
        compare_rows(corrupt)


def test_narrow_bootstrap_cannot_claim_confidence_from_single_day():
    rows=[{"date":"2026-11-01", "advanced":1,
           "basic":2, "actual":0}] * 10
    result=_interval(rows, "advanced","basic","actual")
    assert result["status"]=="insufficient_independent_dates"
    assert result["low"] is None


def test_cli_new_comparison_is_research_only():
    args=build_parser().parse_args(["advanced-score-compare"])
    assert args.command=="advanced-score-compare"
    result=compare_rows([])
    assert result["no_public_predictions"] is True
    assert result["2026_not_a_blind_unseen_test"] is True
    assert result["model_promoted"] is False
