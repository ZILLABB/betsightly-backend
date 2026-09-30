"""Individual family predictions are observations, not champion promotions."""
from leagues import ml_models


class _Model:
    def __init__(self, probabilities):
        self.probabilities = probabilities

    def predict_proba(self, features):
        return [self.probabilities]


def test_runtime_blend_records_individual_supported_families(monkeypatch):
    state = {
        "models": {
            "match_result": [("xgb", _Model([.25, .20, .55])),
                             ("lgbm", _Model([.30, .25, .45]))],
            "over_1_5": [("xgb", _Model([.24, .76]))],
        },
        "calibrators": {},
        "meta": {"result_classes": {"0": "Away Win", "1": "Draw",
                                     "2": "Home Win"}},
    }
    monkeypatch.setattr(ml_models, "_load", lambda: state)
    monkeypatch.setattr(ml_models, "build_features", lambda fixture, index: [1.0])
    result = ml_models.predict_fixture({
        "team_type": "CLUB", "odds": {"implied": {"home_win": .55}}}, None)
    families = result["family_probabilities"]
    assert families["xgb"]["home_win"] == .55
    assert families["lgbm"]["away_win"] == .30
    assert families["xgb"]["over_1_5"] == .76
    assert "nn" not in families and "catboost" not in families
    assert result["home_win"] == .50
    assert ml_models.market_probability(result, "btts_yes") is None
