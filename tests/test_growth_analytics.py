from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from growth import analytics as A
from growth.analytics_enrichment import (
    SYSTEM_EVENT, USER_EVENT, classify_event, device_info, request_geo,
    traffic_source,
)
from growth.models import GrowthEvent


@pytest.fixture()
def analytics_db(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    GrowthEvent.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(A, "engine", engine)
    monkeypatch.setattr(A, "SessionLocal", Session)
    monkeypatch.setattr(A, "ensure_tables", lambda: True)
    A._cache.update({"key": None, "at": 0.0, "value": None})
    yield Session, engine
    engine.dispose()


def test_event_ingestion_is_deduplicated_and_keeps_product_context(analytics_db):
    Session, _ = analytics_db
    payload = dict(
        event_type="builder_generated", visitor_id="visitor-a",
        session_id="session-a", event_id="one-action", path="/build-slip",
        tier="week", target_odds=100, booking_status="FULL",
        leg_count=9, actual_odds=103.6, user_agent="Android Mobile",
    )
    assert A.record(**payload)
    assert A.record(**payload)
    db = Session()
    try:
        rows = db.query(GrowthEvent).all()
        assert len(rows) == 1
        assert rows[0].target_odds == 100
        assert rows[0].device_category == "mobile"
        assert rows[0].os_family == "Android"
    finally:
        db.close()


def test_date_filter_and_new_vs_returning(analytics_db):
    Session, _ = analytics_db
    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)
    visitor = A._visitor_hash("", "", today.isoformat(), "returning-user")
    db = Session()
    try:
        db.add(GrowthEvent(event_date=yesterday.isoformat(), event_type="pageview",
                           visitor_hash=visitor, is_new_visitor=True))
        db.add_all([
            GrowthEvent(event_date=today.isoformat(), event_type="prediction_viewed",
                        visitor_hash=visitor, is_new_visitor=False),
            GrowthEvent(event_date=today.isoformat(), event_type="builder_opened",
                        visitor_hash=visitor, is_new_visitor=False),
            GrowthEvent(event_date=today.isoformat(), event_type="builder_generated",
                        visitor_hash=visitor, is_new_visitor=False),
        ])
        db.commit()
    finally:
        db.close()
    result = A.summary(1, today.isoformat(), today.isoformat())
    assert result["totals"]["visitors"] == 1
    assert result["totals"]["new_visitors"] == 0
    assert result["totals"]["returning_visitors"] == 1
    assert result["funnels"]["prediction"][0]["count"] == 1
    assert result["funnels"]["builder"][0]["count"] == 1


def test_retention_and_empty_installation_are_safe(analytics_db):
    Session, _ = analytics_db
    empty = A.summary(7)
    assert empty["totals"]["visitors"] == 0
    assert empty["booking"]["attempts"] == 0

    today = datetime.now(timezone.utc).date()
    first = today - timedelta(days=3)
    visitor = "stable-hash"
    db = Session()
    try:
        db.add_all([
            GrowthEvent(event_date=first.isoformat(), event_type="pageview",
                        visitor_hash=visitor, is_new_visitor=True),
            GrowthEvent(event_date=(first + timedelta(days=1)).isoformat(),
                        event_type="pageview", visitor_hash=visitor,
                        is_new_visitor=False),
            GrowthEvent(event_date=today.isoformat(), event_type="pageview",
                        visitor_hash=visitor, is_new_visitor=False),
        ])
        db.commit()
    finally:
        db.close()
    A._cache["at"] = 0
    result = A.summary(7)
    assert result["retention"]["d1"] == {
        "rate": 1.0, "returned": 1, "eligible": 1,
    }


def test_booking_health_and_no_code_rate(analytics_db):
    _, engine = analytics_db
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE tier_bookings (publish_date VARCHAR(10), tier VARCHAR(24),"
            " status VARCHAR(16), booking_status VARCHAR(24),"
            " actual_sportybet_odds FLOAT, detail TEXT)"))
        today = datetime.now(timezone.utc).date().isoformat()
        conn.execute(text(
            "INSERT INTO tier_bookings VALUES "
            "(:d,'2_odds','active','FULL',2.1,'{}'),"
            "(:d,'5_odds','unavailable','UNAVAILABLE',NULL,:detail)"),
            {"d": today, "detail": '{"reason":"MARKET_NOT_FOUND"}'})
    A._cache["at"] = 0
    booking = A.summary(1)["booking"]
    assert booking["attempts"] == 2
    assert booking["full"] == 1
    assert booking["no_code_rate"] == 0.5
    assert booking["failures"][0]["reason"] == "MARKET_NOT_FOUND"


def test_geo_enrichment_uses_trusted_edge_headers_only():
    geo = request_geo({
        "x-vercel-id": "iad1::abc", "x-vercel-ip-country": "ng",
        "x-vercel-ip-country-region": "LA", "x-vercel-ip-city": "Lagos",
        "x-vercel-ip-timezone": "Africa/Lagos",
    })
    assert geo == {"country_code": "NG", "region": "LA", "city": "Lagos",
                   "timezone": "Africa/Lagos", "geo_source": "vercel"}
    missing = request_geo({}, "Africa/Lusaka")
    assert missing["country_code"] is None
    assert missing["region"] is None and missing["city"] is None
    assert missing["timezone"] == "Africa/Lusaka"
    spoofed = request_geo({"x-vercel-ip-country": "US"})
    assert spoofed["country_code"] is None


@pytest.mark.parametrize("ua,device,os_name,browser", [
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1", "mobile", "iOS", "Safari"),
    ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/125.0 Mobile Safari/537.36", "mobile", "Android", "Chrome"),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0 Safari/537.36", "desktop", "Windows", "Chrome"),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0 Safari/537.36 Edg/125.0", "desktop", "Windows", "Edge"),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 Version/17.5 Safari/605.1.15", "desktop", "macOS", "Safari"),
    ("", "unknown", "unknown", "Unknown"),
])
def test_device_detection(ua, device, os_name, browser):
    assert device_info(ua) == {"device_type": device,
                               "operating_system": os_name, "browser": browser}


@pytest.mark.parametrize("source,medium,referrer,expected", [
    (None, None, "", "Direct"),
    (None, None, "https://www.google.com/search?q=betsightly", "Google Organic"),
    ("google", "cpc", "", "Google Ads"),
    ("telegram", "social", "", "Telegram"),
    (None, None, "https://wa.me/123", "WhatsApp"),
    (None, None, "https://partner.example/picks", "Referral"),
])
def test_traffic_source_quality_classification(source, medium, referrer, expected):
    assert traffic_source(source, medium, referrer)[0] == expected


def test_system_events_never_become_visitors(analytics_db):
    assert classify_event("pageview") == USER_EVENT
    assert classify_event("scheduler_job_completed") == SYSTEM_EVENT
    assert A.record(event_type="pageview", visitor_id="human", session_id="visit")
    assert A.record(event_type="booking_code_generated", visitor_id="human",
                    session_id="visit")
    result = A.summary(1)
    assert result["totals"]["visitors"] == 1
    assert result["totals"]["events"] == 1
    assert result["totals"]["system_events"] == 1


def test_repeated_copy_actions_do_not_exceed_one_hundred_percent(analytics_db):
    common = dict(visitor_id="person", session_id="visit", booking_id="code-1",
                  product_area="TWO_ODDS")
    assert A.record(event_type="booking_code_viewed", event_id="view", **common)
    assert A.record(event_type="booking_code_copied", event_id="copy-1", **common)
    assert A.record(event_type="booking_code_copied", event_id="copy-2", **common)
    result = A.summary(1)
    assert result["totals"]["total_copy_actions"] == 2
    assert result["totals"]["unique_code_copiers"] == 1
    assert result["totals"]["unique_codes_copied"] == 1
    assert result["totals"]["code_copy_rate"] == 1.0


def test_prediction_builder_and_rollover_funnels_are_independent(analytics_db):
    journeys = {
        "prediction": [("pageview", "PREDICTIONS"),
                       ("prediction_viewed", "PREDICTIONS"),
                       ("booking_code_viewed", "TWO_ODDS"),
                       ("booking_code_copied", "TWO_ODDS")],
        "builder": [("builder_opened", "BUILD_SLIP"),
                    ("builder_target_selected", "BUILD_SLIP"),
                    ("builder_generated", "BUILD_SLIP"),
                    ("booking_code_viewed", "BUILD_SLIP")],
        "rollover": [("rollover_viewed", "ROLLOVER"),
                     ("booking_code_viewed", "ROLLOVER"),
                     ("booking_code_copied", "ROLLOVER")],
    }
    for visitor, steps in journeys.items():
        for index, (event, area) in enumerate(steps):
            assert A.record(event_type=event, visitor_id=visitor,
                            session_id=f"{visitor}-session", event_id=f"{visitor}-{index}",
                            booking_id=f"{visitor}-code", product_area=area)
    result = A.summary(1)
    assert [x["count"] for x in result["funnels"]["prediction"]] == [3, 1, 1, 1, 0]
    assert [x["count"] for x in result["funnels"]["builder"]] == [1, 1, 1, 1, 0, 0]
    assert [x["count"] for x in result["funnels"]["rollover"]] == [1, 1, 1, 0]
    assert all((row["conversion"] is None or row["conversion"] <= 1)
               for funnel in result["funnels"].values() for row in funnel)


def test_system_event_tomorrow_does_not_create_retention(analytics_db):
    Session, _ = analytics_db
    today = datetime.now(timezone.utc).date()
    visitor = "stable-person"
    db = Session()
    try:
        db.add_all([
            GrowthEvent(event_date=(today - timedelta(days=1)).isoformat(),
                        event_type="pageview", event_class=USER_EVENT,
                        visitor_hash=visitor),
            GrowthEvent(event_date=today.isoformat(),
                        event_type="booking_code_generated", event_class=SYSTEM_EVENT,
                        visitor_hash=visitor),
        ])
        db.commit()
    finally:
        db.close()
    result = A.summary(2)
    assert result["retention"]["d1"]["returned"] == 0
