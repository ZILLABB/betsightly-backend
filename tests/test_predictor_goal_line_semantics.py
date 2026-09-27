from leagues.predictor import predict


BASE = {
    "home_win": 0.45,
    "draw": 0.27,
    "away_win": 0.28,
    "avg_goals": 2.5,
    "over_1_5": 0.72,
    "over_2_5": 0.52,
    "btts": 0.50,
}


def fixture(line, over):
    return {
        "match_id": f"line-{line}",
        "home": {"name": "Home"},
        "away": {"name": "Away"},
        "competition": {},
        "odds": {
            "implied_over": over,
            "implied_under": 1.0 - over,
            "ou_line": line,
        },
    }


def test_exact_2_5_quote_can_anchor_over_2_5_directly():
    result = predict(
        fixture(2.5, 0.40),
        BASE,
        None,
    )

    assert result["probabilities"]["over_2_5"] == 0.40


def test_3_5_quote_is_not_mislabeled_as_over_2_5():
    result = predict(
        fixture(3.5, 0.20),
        BASE,
        None,
    )

    # 20% Over 3.5 is not 20% Over 2.5.
    assert result["probabilities"]["over_2_5"] != 0.20
    assert result["probabilities"]["over_2_5"] > 0.20


def test_1_5_quote_is_not_mislabeled_as_over_2_5():
    result = predict(
        fixture(1.5, 0.70),
        BASE,
        None,
    )

    # 70% Over 1.5 must not become 70% Over 2.5.
    assert result["probabilities"]["over_2_5"] != 0.70
    assert result["probabilities"]["over_2_5"] < 0.70
