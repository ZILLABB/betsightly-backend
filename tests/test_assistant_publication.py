"""Authenticated assistant publishing is preview-first and never silently repeats."""
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from leagues import assistant_publication as agent
from leagues import editorial_manual as editorial


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("BETSIGHTLY_ASSISTANT_PUBLISH_KEY", "test-secret-of-at-least-32-chars-1234567890")


def _request(token="test-secret-of-at-least-32-chars-1234567890"):
    return Request({"type": "http", "method": "POST", "path": "/growth/manual-tiers/assistant/preview",
                    "headers": [(b"x-betsightly-assistant-key", token.encode())]})


def _install(monkeypatch, warnings=None):
    lines = "sr:match:one,over_1_5\nsr:match:two,home_win"
    monkeypatch.setattr(editorial, "_today", lambda: "2026-10-20")
    monkeypatch.setattr(editorial, "import_share_code", lambda code, tier, convert_special=False: {
        "status": "IMPORTED_NOT_PUBLISHED", "original_leg_count": 2,
        "unresolved_count": 0, "converted_features": [],
        "lines": lines,
    })
    monkeypatch.setattr(editorial, "preview", lambda tier, value: {
        "status": "PREVIEW", "date": "2026-10-20",
        "games": [
            {"sportybet_event_id": "sr:match:one", "market": "over_1_5"},
            {"sportybet_event_id": "sr:match:two", "market": "home_win"},
        ],
        "total_odds": 5.45, "cross_tier_warnings": warnings or [],
    })
    return lines


def test_missing_key_fails_closed_and_wrong_key_is_rejected(monkeypatch):
    agent.require_assistant_key(_request())
    with pytest.raises(HTTPException) as wrong:
        agent.require_assistant_key(_request("unauthorized"))
    assert wrong.value.status_code == 401
    monkeypatch.delenv("BETSIGHTLY_ASSISTANT_PUBLISH_KEY")
    with pytest.raises(HTTPException) as missing:
        agent.require_assistant_key(_request())
    assert missing.value.status_code == 503


def test_preview_is_non_mutating_and_publish_needs_correct_signed_token(monkeypatch):
    _install(monkeypatch)
    body = agent.AssistantTicket(tier="5_odds", code="ABCD12", expected_legs=2)
    report = agent.preview_assistant_ticket(body)
    assert report["status"] == "PREVIEW_ONLY"
    assert report["frontend_changed"] is False
    assert report["leg_count"] == 2
    assert report["publish_confirmed"] is False
    assert agent._decode_token(report["preview_token"])["code"] == "ABCD12"
    with pytest.raises(HTTPException, match="preview token"):
        agent._decode_token(report["preview_token"][:-4] + "AAAA")
    with pytest.raises(ValueError, match="Preview is for another"):
        agent.publish_assistant_ticket(agent.AssistantPublish(
            tier="5_odds", code="DIFF12", expected_legs=2,
            preview_token=report["preview_token"],
            confirmation=agent.CONFIRMATION,
        ))


def test_preview_rejects_duplicate_cross_tier_and_miscount(monkeypatch):
    _install(monkeypatch, warnings=[{"fixture": "Duplicate", "also_in_tiers": ["banker"]}])
    with pytest.raises(ValueError, match="already used"):
        agent.preview_assistant_ticket(agent.AssistantTicket(
            tier="5_odds", code="ABCD12", expected_legs=2,
        ))
    with pytest.raises(ValueError, match="exactly"):
        agent.preview_assistant_ticket(agent.AssistantTicket(
            tier="5_odds", code="ABCD12", expected_legs=3,
        ))


def test_confirmed_publish_uses_locked_no_overlap_path_and_new_code(monkeypatch):
    _install(monkeypatch)
    ticket = agent.AssistantTicket(tier="5_odds", code="ABCD12", expected_legs=2)
    report = agent.preview_assistant_ticket(ticket)
    params = {}

    def approved_publish(tier, lines, **kwargs):
        params.update(kwargs)
        assert tier == "5_odds"
        assert len(lines.splitlines()) == 2
        return {
            "status": "PUBLISHED", "leg_count": 2,
            "share_code": "NEWCOD", "total_odds": 5.40,
        }
    monkeypatch.setattr(editorial, "publish", approved_publish)
    published = agent.publish_assistant_ticket(agent.AssistantPublish(
        tier="5_odds", code="ABCD12", expected_legs=2,
        preview_token=report["preview_token"],
        confirmation=agent.CONFIRMATION,
    ))
    assert params["strict_no_overlap"] is True
    assert params["min_publish_odds"] == round(5.45 * 0.95, 3)
    assert published["source"] == "assistant_verified_import"
    assert published["share_code_rebooked"] is True
    assert published["calibration_unchanged"] is True


def test_expired_token_is_refused(monkeypatch):
    _install(monkeypatch)
    issued = agent.preview_assistant_ticket(agent.AssistantTicket(
        tier="5_odds", code="ABCD12", expected_legs=2,
    ))
    current = int(agent.time.time())
    monkeypatch.setattr(agent.time, "time", lambda: current + 601)
    with pytest.raises(HTTPException, match="preview token"):
        agent._decode_token(issued["preview_token"])


def test_under_market_rejected_even_when_share_code_resolves(monkeypatch):
    _install(monkeypatch)
    monkeypatch.setattr(editorial, "import_share_code", lambda code, tier, convert_special=False: {
        "status": "IMPORTED_NOT_PUBLISHED", "original_leg_count": 2,
        "unresolved_count": 0, "converted_features": [],
        "lines": "sr:match:one,under_3_5\nsr:match:two,home_win",
    })
    with pytest.raises(ValueError, match="Under-goals"):
        agent.preview_assistant_ticket(agent.AssistantTicket(
            tier="5_odds", code="ABCD12", expected_legs=2,
        ))
