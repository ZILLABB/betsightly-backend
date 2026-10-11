"""ROI must be real-price, settled, de-duplicated, and transparent."""
from leagues.verified_roi_audit import audited_market_roi, production_roi_report


def _leg(fid, status, odds=1.4, real=True, market="over_1_5", prob=.72):
    return {"match_id": fid, "market": market, "status": status,
            "odds": odds, "odds_are_real": real, "confidence": prob,
            "kickoff": "2026-10-05T16:00:00Z"}


def _slip(category, picks, status="pending", odds=1.96, slip_id=1):
    return {"id": slip_id, "date": "2026-10-05",
            "category": category, "policy_version": "v1",
            "status": status, "total_odds": odds, "picks": picks,
            "created_at": "2026-10-05T08:00:00Z"}


def test_duplicate_fixture_market_does_not_double_inflate_profit():
    slips = [
        _slip("banker", [_leg("A", "won", 1.4)], "won", 1.4, 1),
        _slip("over_1_5", [_leg("A", "won", 1.4),
                             _leg("B", "lost", 1.5)], "lost", 2.1, 2)
    ]
    result = audited_market_roi(slips)
    m = result["markets"]["over_1_5"]
    assert m["settled"] == 2
    assert m["flat_one_unit_net"] == -0.6
    assert result["excluded"]["duplicate_fixture_market"] == 1
    assert result["products"]["over_1_5"]["settled"] == 2
    assert result["products"]["banker"]["settled"] == 1


def test_pending_void_and_estimated_quotes_are_excluded():
    slip = _slip("2_odds", [
        _leg("A", "pending"),
        _leg("B", "void"),
        _leg("C", "won", 1.5, real=False),
        _leg("D", "lost", 1.6),
    ], status="pending")
    report = audited_market_roi([slip])
    assert report["distinct_settled_fixture_markets"] == 1
    assert report["markets"]["over_1_5"]["flat_one_unit_net"] == -1
    assert report["excluded"]["unsettled_or_void"] == 2
    assert report["excluded"]["unverified_or_missing_price"] == 1
    assert "2_odds" not in report["products"]


def test_official_slip_and_independent_singles_are_not_confused():
    result = audited_market_roi([
        _slip("5_odds", [_leg("A", "won"), _leg("B", "won")],
              status="won", odds=5.12),
        _slip("over_1_5", [_leg("C", "won", 1.3),
                             _leg("D", "lost", 1.4)], status="lost",
              odds=1.82, slip_id=2),
    ])
    assert result["products"]["5_odds"]["flat_one_unit_net"] == 4.12
    assert result["products"]["over_1_5"]["flat_one_unit_net"] == -0.7
    assert result["actual_wager_profit_claim"] is False


def test_small_samples_never_claim_profitable_model_promotion():
    report = audited_market_roi([
        _slip("banker", [_leg("A", "won", 1.2)], status="won", odds=1.2)
    ])
    m = report["markets"]["over_1_5"]
    assert m["evidence_state"] == "INSUFFICIENT"
    assert report["mode"] == "SHADOW_EVIDENCE_ONLY"
    assert report["official_publications_unchanged"]


def test_previously_archived_confidence_is_not_recomputed():
    m = audited_market_roi([
        _slip("banker", [_leg("A", "lost", 1.4, prob=.81)],
              status="lost", odds=1.4),
    ])["markets"]["over_1_5"]
    assert m["mean_published_probability"] == .81
    assert m["confidence_bias"] == .81


def test_database_reader_is_bounded_and_read_only(monkeypatch):
    from leagues import picks_db
    history_calls = []
    monkeypatch.setattr(picks_db, "get_history",
                        lambda limit_days: history_calls.append(limit_days) or [])
    report = production_roi_report(days=600)
    assert history_calls == [365]
    assert report["lookback_days"] == 365
    assert report["distinct_settled_fixture_markets"] == 0
