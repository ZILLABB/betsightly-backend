from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from growth import analytics as A
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


def test_date_filter_funnel_and_new_vs_returning(analytics_db):
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
    assert [row["count"] for row in result["funnel"][:4]] == [1, 1, 1, 1]


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
