"""API-Football HTTP-200 account errors must never become empty-slate caches."""
from datetime import datetime
import json

from services.apifootball_service import APIFootballService


def _service(tmp_path):
    obj = APIFootballService.__new__(APIFootballService)
    obj.api_key = "test-key"
    obj.timeout = 5
    obj.cache_dir = tmp_path
    return obj


def test_error_payload_is_retained_for_callers_without_local_success_cache(
    monkeypatch, tmp_path,
):
    service = _service(tmp_path)

    class SuspendedResponse:
        status_code = 200
        headers = {}

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "errors": {"access": "Your account is suspended"},
                "response": [],
            }

    monkeypatch.setattr(
        "services.api_football_gateway.api_football_get",
        lambda *args, **kwargs: SuspendedResponse(),
    )
    data = service._get("fixtures", {"date": "2026-10-08"}, use_cache=False)
    assert data["response"] == []
    assert "suspended" in data["errors"]["access"]


def test_daily_fixtures_never_cache_provider_or_quota_error(monkeypatch, tmp_path):
    service = _service(tmp_path)
    cached = []
    monkeypatch.setattr(service, "_read_daily_cache", lambda *args: None)
    monkeypatch.setattr(service, "_get", lambda *args, **kwargs: {
        "errors": {"access": "Your account is suspended"},
        "response": [],
    })
    monkeypatch.setattr(
        service, "_write_daily_cache",
        lambda *args: cached.append(args),
    )
    assert service.get_daily_fixtures("2026-10-08") == []
    assert cached == []


def test_daily_fixtures_still_cache_a_legitimate_empty_slate(monkeypatch, tmp_path):
    service = _service(tmp_path)
    cached = []
    monkeypatch.setattr(service, "_read_daily_cache", lambda *args: None)
    monkeypatch.setattr(
        service, "_get",
        lambda *args, **kwargs: {"errors": {}, "response": []},
    )
    monkeypatch.setattr(
        service, "_write_daily_cache",
        lambda *args: cached.append(args),
    )
    assert service.get_daily_fixtures("2026-10-08") == []
    assert len(cached) == 1


def test_previously_cached_provider_error_is_invalidated(tmp_path):
    service = _service(tmp_path)
    today = datetime.now().strftime("%Y-%m-%d")
    path = tmp_path / f"{service._daily_cache_key(today)}.json"
    path.write_text(json.dumps({
        "fixture_date": today,
        "cached_at": datetime.now().isoformat(),
        "data": {"response": [], "errors": {"quota": "local_guard"}},
    }), encoding="utf-8")
    assert service._read_daily_cache(today) is None
    assert not path.exists()
