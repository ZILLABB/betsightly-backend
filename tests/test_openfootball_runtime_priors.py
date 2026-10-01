from datetime import datetime, timezone

import pytest

from leagues import base_rates
from leagues import openfootball_runtime_priors as priors
from leagues.espn_history_fetch import HistoryMonthUnavailable


SAMPLE = """= Test League 2024/25

  Sat Oct 5 2024
    17:00  Alpha FC v Beta FC 2-1 (1-0)
  Sat Oct 12
    17:00  Gamma FC v Delta FC 1-1 (0-0)
"""


def test_verified_prior_registry_is_slug_keyed_and_keeps_j2_fail_closed():
    assert priors.supports("aus.1")
    assert priors.supports("cze.1")
    assert priors.supports("pol.1")
    assert priors.supports("rou.1")
    assert priors.supports("srb.1")
    assert priors.supports("uefa.europa.conf")
    assert not priors.supports("jpn.2")


def test_pinned_prior_parser_never_claims_current_team_form(monkeypatch):
    priors._parsed_source.cache_clear()
    monkeypatch.setattr(
        priors,
        "_request_text",
        lambda url: SAMPLE,
    )

    scores = priors.finished_scores(
        "cze.1",
        lookback_days=1000,
    )

    assert scores == [(2, 1), (1, 1)]

    state = priors.status()["cze.1"]
    assert state["source"] == priors.SOURCE_NAME
    assert state["current_team_form"] is False
    assert state["as_of_replay_allowed"] is False


def test_pinned_prior_is_disabled_for_as_of_replay():
    assert priors.finished_scores(
        "cze.1",
        as_of=datetime(
            2025,
            1,
            1,
            tzinfo=timezone.utc,
        ),
    ) == []

    assert (
        priors.status()["cze.1"]["status"]
        == "DISABLED_FOR_AS_OF_REPLAY"
    )


def test_base_rates_uses_verified_prior_on_clean_empty_espn(monkeypatch):
    from leagues import history_months

    monkeypatch.setattr(
        history_months,
        "finished_matches",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        priors,
        "finished_scores",
        lambda slug, **kwargs: [(2, 1), (1, 0)],
    )

    assert base_rates._fetch_finished_range(
        "cze.1",
        "20260901",
        "20260930",
    ) == [(2, 1), (1, 0)]


def test_base_rates_uses_verified_prior_on_permanent_espn_gap(monkeypatch):
    from leagues import history_months

    def unavailable(*args, **kwargs):
        raise HistoryMonthUnavailable(
            "unsupported",
            permanent=True,
            status_code=400,
        )

    monkeypatch.setattr(
        history_months,
        "finished_matches",
        unavailable,
    )
    monkeypatch.setattr(
        priors,
        "finished_scores",
        lambda slug, **kwargs: [(3, 1)],
    )

    assert base_rates._fetch_finished_range(
        "pol.1",
        "20260901",
        "20260930",
    ) == [(3, 1)]


def test_base_rates_does_not_mask_transient_history_failure(monkeypatch):
    from leagues import history_months

    def unavailable(*args, **kwargs):
        raise HistoryMonthUnavailable(
            "temporary",
            permanent=False,
            status_code=503,
        )

    monkeypatch.setattr(
        history_months,
        "finished_matches",
        unavailable,
    )

    with pytest.raises(HistoryMonthUnavailable):
        base_rates._fetch_finished_range(
            "cze.1",
            "20260901",
            "20260930",
        )
