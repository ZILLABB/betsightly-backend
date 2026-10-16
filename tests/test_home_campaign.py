"""Homepage campaign publication never modifies predictions or growth posts."""
from datetime import date

import pytest

from growth.home_campaign import current_campaign, validate_campaign


GOOD = {
    "enabled": True, "reviewed": True,
    "eyebrow": "European football",
    "headline": "Champions League week",
    "description": "Upcoming verified UCL fixtures.",
    "cta_text": "See predictions",
    "cta_path": "/predictions",
    "starts_on": "2026-10-16",
    "ends_on": "2026-10-22",
    "source_url": "https://www.uefa.com/uefachampionsleague/",
}


def test_active_campaign_only_within_wat_window():
    validated = validate_campaign(GOOD)
    assert current_campaign(validated, date(2026, 10, 16))["headline"] == GOOD["headline"]
    assert current_campaign(validated, date(2026, 10, 22))["headline"] == GOOD["headline"]
    assert current_campaign(validated, date(2026, 10, 23)) is None
    assert current_campaign(validated, date(2026, 10, 15)) is None


def test_default_off_and_stale_records_cannot_generate_fake_spotlight():
    assert current_campaign(None, date(2026, 10, 16)) is None
    assert current_campaign({**GOOD, "enabled": False}, date(2026, 10, 16)) is None
    assert current_campaign({**GOOD, "reviewed": False}, date(2026, 10, 16)) is None
    assert current_campaign({**GOOD, "headline": ""}, date(2026, 10, 16)) is None


@pytest.mark.parametrize("overrides", [
    {"cta_path": "https://evil.example"},
    {"cta_path": "//evil.example"},
    {"source_url": "javascript:alert(1)"},
    {"source_url": "http://www.uefa.com"},
    {"enabled": "true"},
    {"reviewed": False},
    {"headline": "<" * 90},
    {"starts_on": "2026-10-25", "ends_on": "2026-10-20"},
    {"ends_on": "2027-05-20"},
    {"eyebrow": "UCL\nINJECTION"},
    {"unrecognized": "hello"},
])
def test_invalid_or_unreviewed_campaign_cannot_publish(overrides):
    with pytest.raises(ValueError):
        validate_campaign({**GOOD, **overrides})


def test_public_campaign_projection_omits_review_state_and_evidence_url():
    c = current_campaign(GOOD, date(2026, 10, 16))
    assert c is not None
    assert "source_url" not in c
    assert "reviewed" not in c
    assert "enabled" not in c
    assert set(c) == {
        "eyebrow", "headline", "description", "cta_text",
        "cta_path", "starts_on", "ends_on",
    }
