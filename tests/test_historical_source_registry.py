from leagues import historical_source_registry as registry


def test_verified_openfootball_sources_expand_results_history_only():
    for league_id in (1, 2, 3, 11, 13, 848):
        source = registry.source_for(league_id)
        assert source is not None
        assert source.verification == registry.VERIFIED
        assert source.results_history is True
        assert source.bookmaker_odds_history is False
        assert registry.eligible_for_current_market_feature_training(source) is False


def test_unresolved_sources_fail_closed():
    for league_id in (265, 292, 307):
        source = registry.source_for(league_id)
        assert source is not None
        assert source.source_class == registry.UNRESOLVED
        assert source.results_history is False
        assert registry.eligible_for_current_market_feature_training(source) is False


def test_registry_summary_keeps_results_and_market_coverage_separate():
    payload = registry.summary()

    assert payload["tracked_gap_count"] == 9
    assert payload["results_history_covered_count"] == 6
    assert payload["odds_backed_covered_count"] == 0
    assert payload["current_market_model_eligible_count"] == 0
    assert payload["unresolved_count"] == 3
