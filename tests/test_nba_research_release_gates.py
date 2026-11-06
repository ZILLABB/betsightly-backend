"""Never promote NBA research from a small or underperforming paper sample."""
from basketball import research_release_gates as gates


def _sample(n, *, strong=False):
    fixtures, records = [], {x: [] for x in (
        "moneyline", "moneyline_finals", "opening_score", "opening_score_finals",
        "early_advanced", "early_advanced_finals")}
    for i in range(n):
        gid = str(100000 + i)
        fixtures.append({"game_id": gid, "status": "final",
                         "home_score": 110, "away_score": 105})
        records["moneyline"].append({
            "game_id": gid, "probability_home_win": .96 if strong else .45,
            "previous_season_home_baseline": .55})
        records["opening_score"].append({
            "game_id": gid, "predicted_total": 217.,
            "league_baseline_total": 228.})
        records["early_advanced"].append({
            "game_id": gid, "predicted_total": 210.,
            "original_predicted_total": 217.})
        for kind in ("moneyline", "opening_score", "early_advanced"):
            records[kind + "_finals"].append({"game_id": gid})
    return {"fixtures": fixtures, "records": records}


def test_small_sample_cannot_promote_even_better_brier(monkeypatch):
    monkeypatch.setattr(gates, "inspect_bundle", lambda _: {"status": "ok"})
    result = gates.grade_models(_sample(16, strong=True))
    assert result["moneyline"]["settled_games"] == 16
    assert result["moneyline"]["brier"] < result["moneyline"]["baseline_brier"]
    assert result["moneyline"]["accepted"] is False
    assert result["advanced_score"]["paired_mae_gain"] < 0
    assert result["advanced_score"]["accepted"] is False
    assert result["public_predictions_enabled"] is False


def test_large_sample_alone_does_not_enable_public_betting(monkeypatch):
    monkeypatch.setattr(gates, "inspect_bundle", lambda _: {"status": "ok"})
    result = gates.grade_models(_sample(150, strong=True))
    assert result["moneyline"]["accepted"] is True
    assert result["advanced_score"]["accepted"] is False
    assert "closing_line_market_gate" in result["release_blockers"]
    assert "verified_operations_and_manual_approval" in result["release_blockers"]
    assert result["not_bookable"] is True
