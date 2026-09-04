from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from growth import posthog_adapter as adapter


class FakeResponse:
    def __init__(self, results):
        self._results = results
    def raise_for_status(self):
        return None
    def json(self):
        return {"results": self._results}


def test_posthog_adapter_queries_once_then_uses_cache(monkeypatch):
    db = create_engine("sqlite://", poolclass=StaticPool,
                       connect_args={"check_same_thread": False})
    monkeypatch.setattr(adapter, "engine", db)
    monkeypatch.setenv("POSTHOG_PROJECT_ID", "42")
    monkeypatch.setenv("POSTHOG_PERSONAL_API_KEY", "secret")
    adapter._memory.clear()
    calls = []
    def transport(url, **kwargs):
        calls.append((url, kwargs))
        query = kwargs["json"]["query"]["query"]
        if "GROUP BY toDate" in query:
            return FakeResponse([["2026-09-03", 10, 11, 20, 3, 2]])
        if "GROUP BY 1" in query:
            return FakeResponse([["NG", 8, 12, 3, 9, 6, 4, 3, 2, 1]])
        if "countIf(yesterday>0)" in query:
            return FakeResponse([[7, 4]])
        if "arrayExists" in query:
            return FakeResponse([[8, 4, 8, 3, 7, 2, 5, 1, 2, 1]])
        if "FROM (SELECT distinct_id" in query:
            width = (6 if "builder_target_selected" in query else
                     4 if "rollover_viewed" in query else 5)
            return FakeResponse([[10 - i for i in range(width)]])
        if "properties.$is_first_day" in query:
            return FakeResponse([[10, 20, 30, 4]])
        return FakeResponse([[40, 10, 11, 20, 8, 2, 4, 3, 3, 2, 1, 0]])
    first = adapter.summary("2026-09-03", "2026-09-03", transport)
    second = adapter.summary("2026-09-03", "2026-09-03", transport)
    assert first["meta"]["status"] == "fresh"
    assert first["data"]["totals"]["visitors"] == 10
    assert first["data"]["by_country"][0]["key"] == "NG"
    assert second == first
    assert len(calls) == 16


def test_posthog_adapter_is_explicit_when_unconfigured(monkeypatch):
    db = create_engine("sqlite://", poolclass=StaticPool,
                       connect_args={"check_same_thread": False})
    monkeypatch.setattr(adapter, "engine", db)
    monkeypatch.delenv("POSTHOG_PROJECT_ID", raising=False)
    monkeypatch.delenv("POSTHOG_PERSONAL_API_KEY", raising=False)
    adapter._memory.clear()
    result = adapter.summary("2026-09-01", "2026-09-02")
    assert result["meta"]["status"] == "unavailable"
    assert result["meta"]["reason"] == "not_configured"


def test_posthog_adapter_serves_stale_cache_on_query_failure(monkeypatch):
    db = create_engine("sqlite://", poolclass=StaticPool,
                       connect_args={"check_same_thread": False})
    monkeypatch.setattr(adapter, "engine", db)
    monkeypatch.setenv("POSTHOG_PROJECT_ID", "42")
    monkeypatch.setenv("POSTHOG_PERSONAL_API_KEY", "secret")
    monkeypatch.setattr(adapter, "CACHE_SECONDS", 0)
    adapter._memory.clear()
    adapter._write_cache("posthog:2026-08-01:2026-08-02", {"totals": {"visitors": 9}},
                         datetime.now(timezone.utc))
    def broken(*args, **kwargs):
        raise TimeoutError("provider unavailable")
    result = adapter.summary("2026-08-01", "2026-08-02", broken)
    assert result["data"]["totals"]["visitors"] == 9
    assert result["meta"]["source"] == "posthog"
    assert result["meta"]["status"] == "stale"


def test_posthog_adapter_rejects_malformed_provider_rows(monkeypatch):
    db = create_engine("sqlite://", poolclass=StaticPool,
                       connect_args={"check_same_thread": False})
    monkeypatch.setattr(adapter, "engine", db)
    monkeypatch.setenv("POSTHOG_PROJECT_ID", "42")
    monkeypatch.setenv("POSTHOG_PERSONAL_API_KEY", "secret")
    adapter._memory.clear()

    # A short totals row previously produced a partially populated, "fresh"
    # dashboard. Shape drift must degrade the provider explicitly instead.
    result = adapter.summary(
        "2026-09-01", "2026-09-02",
        lambda *args, **kwargs: FakeResponse([[1, 2, 3]]),
    )

    assert result["data"] == {}
    assert result["meta"]["status"] == "unavailable"
    assert result["meta"]["reason"] == "query_failed:ValueError"
