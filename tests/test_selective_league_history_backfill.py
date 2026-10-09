"""Under-sampled leagues use genuine older results, never inflated priors."""
from datetime import datetime, timezone

from leagues import base_rates


def test_selective_history_backfill_uses_nonoverlapping_real_scores(monkeypatch):
    calls = []

    def finished(slug, start, end, *, as_of=None):
        calls.append((slug, start, end))
        if slug == "eng.1":
            return [(1, 0)] * (3 if start == "20260825" else 9)
        return [(2, 1)] * 20

    monkeypatch.setattr(base_rates, "_fetch_finished_range", finished)
    report = base_rates.compute_base_rates(
        {"eng.1": "Premier League", "esp.1": "La Liga"},
        as_of=datetime(2026, 10, 9, tzinfo=timezone.utc),
    )
    assert report["eng.1"]["matches"] == 12
    assert report["esp.1"]["matches"] == 20
    assert report["_history_backfill"]["eng.1"]["older_matches"] == 9
    assert report["_history_backfill"]["eng.1"]["ready_for_direct_history"] is True
    assert all(slug != "esp.1" or start == "20260825"
               for slug, start, _ in calls)
    # Recent window starts 45 days ago, extended window ends 46 days ago.
    older = next((start, end) for slug, start, end in calls
                 if slug == "eng.1" and start != "20260825")
    assert older == ("20260412", "20260824")


def test_empty_backfill_cannot_create_fake_samples(monkeypatch):
    monkeypatch.setattr(
        base_rates, "_fetch_finished_range",
        lambda *args, **kwargs: [],
    )
    report = base_rates.compute_base_rates(
        {"eng.1": "Premier League"},
        as_of=datetime(2026, 10, 9, tzinfo=timezone.utc),
    )
    assert "eng.1" not in report
    assert report["_history_backfill"]["eng.1"]["total_matches"] == 0
    assert report["_history_backfill"]["eng.1"]["ready_for_direct_history"] is False


def test_backfill_failure_does_not_discard_recent_real_results(monkeypatch):
    from leagues.espn_history_fetch import HistoryMonthUnavailable
    def source(slug, start, end, *, as_of=None):
        if start == "20260825":
            return [(1, 0)] * 7
        raise HistoryMonthUnavailable("older month not available")

    monkeypatch.setattr(base_rates, "_fetch_finished_range", source)
    report = base_rates.compute_base_rates(
        {"eng.1": "Premier League"},
        as_of=datetime(2026, 10, 9, tzinfo=timezone.utc),
    )
    assert report["eng.1"]["matches"] == 7
    assert report["_history_backfill"]["eng.1"]["status"] == "UNAVAILABLE"
