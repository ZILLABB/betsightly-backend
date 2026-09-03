"""Small, cached PostHog Query API adapter for the protected admin dashboard."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Callable

import requests
from sqlalchemy import Column, DateTime, MetaData, String, Table, Text, select

from database import engine

CACHE_SECONDS = int(os.getenv("POSTHOG_QUERY_CACHE_SECONDS", "300"))
metadata = MetaData()
provider_cache = Table(
    "analytics_provider_cache", metadata,
    Column("cache_key", String(160), primary_key=True),
    Column("payload", Text, nullable=False),
    Column("as_of", DateTime(timezone=True), nullable=False),
)
_memory: dict[str, tuple[float, dict]] = {}


def _config() -> tuple[str | None, str | None, str]:
    return (os.getenv("POSTHOG_PROJECT_ID"), os.getenv("POSTHOG_PERSONAL_API_KEY"),
            os.getenv("POSTHOG_HOST", "https://us.posthog.com").rstrip("/"))


def _query(project: str, key: str, host: str, hogql: str,
           transport: Callable | None = None) -> list:
    sender = transport or requests.post
    response = sender(
        f"{host}/api/projects/{project}/query/",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"query": {"kind": "HogQLQuery", "query": hogql}}, timeout=10,
    )
    response.raise_for_status()
    body = response.json()
    return body.get("results") or []


def _read_cache(cache_key: str) -> tuple[dict | None, datetime | None]:
    metadata.create_all(engine, tables=[provider_cache], checkfirst=True)
    with engine.begin() as conn:
        row = conn.execute(select(provider_cache).where(
            provider_cache.c.cache_key == cache_key)).mappings().first()
    if not row:
        return None, None
    return json.loads(row["payload"]), row["as_of"]


def _write_cache(cache_key: str, payload: dict, as_of: datetime) -> None:
    metadata.create_all(engine, tables=[provider_cache], checkfirst=True)
    with engine.begin() as conn:
        conn.execute(provider_cache.delete().where(provider_cache.c.cache_key == cache_key))
        conn.execute(provider_cache.insert().values(
            cache_key=cache_key, payload=json.dumps(payload, separators=(",", ":")), as_of=as_of))


def _meta(status: str, as_of: datetime | None, reason: str | None = None) -> dict:
    now = datetime.now(timezone.utc)
    if as_of and as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    out = {"source": "posthog", "status": status,
           "as_of": as_of.isoformat() if as_of else None,
           "freshness_seconds": max(0, int((now - as_of).total_seconds())) if as_of else None}
    if reason:
        out["reason"] = reason[:160]
    return out


def _dimension(rows: list) -> list[dict]:
    output = []
    for row in rows:
        values = list(row) + [0] * 10
        visitors, returning, sessions = (int(values[1] or 0), int(values[3] or 0),
                                         int(values[4] or 0))
        prediction, builders = int(values[5] or 0), int(values[6] or 0)
        viewers, copiers, opens = (int(values[7] or 0), int(values[8] or 0),
                                   int(values[9] or 0))
        output.append({
            "key": values[0] or "unknown", "visitors": visitors,
            "count": int(values[2] or 0), "returning": returning,
            "sessions": sessions, "prediction_viewers": prediction,
            "builders": builders, "code_copiers": copiers,
            "prediction_view_rate": round(prediction / visitors, 4) if visitors else None,
            "builder_usage_rate": round(builders / visitors, 4) if visitors else None,
            "copy_conversion": round(min(copiers, viewers) / viewers, 4) if viewers else None,
            "sportybet_open_rate": round(min(opens, viewers) / viewers, 4) if viewers else None,
            "return_rate": round(returning / visitors, 4) if visitors else None,
        })
    return output


def _funnel(rows: list, labels: list[str]) -> list[dict]:
    counts = [int(value or 0) for value in (rows[0] if rows else [])]
    out = []
    previous = None
    for label, count in zip(labels, counts):
        rate = count / previous if previous else (1.0 if count else None)
        out.append({"label": label, "count": count,
                    "conversion": round(rate, 4) if rate is not None else None,
                    "dropoff": round(1 - rate, 4) if rate is not None else None})
        previous = count
    return out


def summary(start: str, end: str, transport: Callable | None = None) -> dict:
    """Return PostHog human analytics, with 5-minute cache and stale-if-error."""
    datetime.strptime(start, "%Y-%m-%d")
    datetime.strptime(end, "%Y-%m-%d")
    project, key, host = _config()
    cache_key = f"posthog:{start}:{end}"
    now_mono = time.monotonic()
    cached = _memory.get(cache_key)
    if cached and now_mono - cached[0] < CACHE_SECONDS:
        return cached[1]
    persisted, persisted_at = _read_cache(cache_key)
    if persisted_at:
        aware = persisted_at if persisted_at.tzinfo else persisted_at.replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - aware).total_seconds() < CACHE_SECONDS:
            result = {"data": persisted, "meta": _meta("fresh", aware)}
            _memory[cache_key] = (now_mono, result)
            return result
    if not project or not key:
        return {"data": persisted or {},
                "meta": _meta("stale" if persisted else "unavailable", persisted_at,
                              "not_configured")}

    where = (f"timestamp >= toDateTime('{start} 00:00:00') AND "
             f"timestamp < addDays(toDateTime('{end} 00:00:00'), 1)")
    totals_sql = f"""
      SELECT count(), uniq(distinct_id),
        uniqIf(toString(properties.$session_id), notEmpty(toString(properties.$session_id))),
        countIf(event = '$pageview'), uniqIf(distinct_id, event = 'prediction_viewed'),
        uniqIf(distinct_id, event = 'rollover_viewed'),
        uniqIf(distinct_id, event = 'builder_opened'),
        uniqIf(distinct_id, event = 'builder_generated'),
        uniqIf(distinct_id, event = 'booking_code_viewed'),
        uniqIf(distinct_id, event = 'booking_code_copied'),
        uniqIf(distinct_id, event = 'sportybet_opened'),
        countIf((event IN ('prediction_viewed','rollover_viewed','builder_opened')
                 AND empty(toString(properties.product_area))) OR
                (event IN ('builder_target_selected','builder_generate_requested','builder_generated')
                 AND (empty(toString(properties.product_area)) OR properties.target_odds IS NULL)) OR
                (event IN ('booking_code_viewed','booking_code_copied','sportybet_opened')
                 AND (empty(toString(properties.product_area)) OR empty(toString(properties.booking_status))
                      OR empty(toString(properties.booking_variant_id)))))
      FROM events WHERE {where}
    """
    daily_sql = f"""
      SELECT toDate(timestamp), uniq(distinct_id),
        uniq(toString(properties.$session_id)), count(),
        countIf(event='builder_generated'), countIf(event='booking_code_copied')
      FROM events WHERE {where} GROUP BY toDate(timestamp) ORDER BY toDate(timestamp)
    """
    def dim_sql(prop: str) -> str:
        return (f"SELECT if(empty(toString({prop})), 'unknown', toString({prop})), "
                "uniq(distinct_id), count(), uniqIf(distinct_id, properties.$is_first_day!=true), "
                "uniq(toString(properties.$session_id)), uniqIf(distinct_id,event='prediction_viewed'), "
                "uniqIf(distinct_id,event='builder_opened'), uniqIf(distinct_id,event='booking_code_viewed'), "
                "uniqIf(distinct_id,event='booking_code_copied'), uniqIf(distinct_id,event='sportybet_opened') "
                f"FROM events WHERE {where} GROUP BY 1 "
                "ORDER BY 2 DESC LIMIT 25")
    def funnel_sql(events: list[str]) -> str:
        measures = ", ".join(
            f"countIf(event='{event}') AS h{i}, minIf(toUnixTimestamp(timestamp), event='{event}') AS t{i}"
            for i, event in enumerate(events))
        conditions, previous = [], None
        for i in range(len(events)):
            current = f"h{i}>0"
            if previous:
                current += f" AND t{i}>={previous}"
            conditions.append(f"countIf({current})")
            previous = f"t{i}"
        return (f"SELECT {', '.join(conditions)} FROM (SELECT distinct_id, {measures} "
                f"FROM events WHERE {where} GROUP BY distinct_id)")
    retention_sql = f"""
      SELECT
        countIf(first_day <= subtractDays(toDate('{end}'), 1)),
        countIf(first_day <= subtractDays(toDate('{end}'), 1) AND arrayExists(x -> x=addDays(first_day,1), days)),
        countIf(first_day <= subtractDays(toDate('{end}'), 3)),
        countIf(first_day <= subtractDays(toDate('{end}'), 3) AND arrayExists(x -> x=addDays(first_day,3), days)),
        countIf(first_day <= subtractDays(toDate('{end}'), 7)),
        countIf(first_day <= subtractDays(toDate('{end}'), 7) AND arrayExists(x -> x=addDays(first_day,7), days)),
        countIf(first_day <= subtractDays(toDate('{end}'), 14)),
        countIf(first_day <= subtractDays(toDate('{end}'), 14) AND arrayExists(x -> x=addDays(first_day,14), days)),
        countIf(first_day <= subtractDays(toDate('{end}'), 30)),
        countIf(first_day <= subtractDays(toDate('{end}'), 30) AND arrayExists(x -> x=addDays(first_day,30), days))
      FROM (SELECT distinct_id, min(toDate(timestamp)) AS first_day,
            groupUniqArray(toDate(timestamp)) AS days FROM events
            WHERE event='$pageview' AND timestamp < addDays(toDateTime('{end} 00:00:00'),1)
            GROUP BY distinct_id) WHERE first_day >= toDate('{start}')
    """
    prediction_return_sql = f"""
      SELECT countIf(yesterday>0), countIf(yesterday>0 AND today>0)
      FROM (SELECT distinct_id,
        countIf(event='prediction_viewed' AND toDate(timestamp)=subtractDays(toDate('{end}'),1)) AS yesterday,
        countIf(event='prediction_viewed' AND toDate(timestamp)=toDate('{end}')) AS today
        FROM events WHERE timestamp >= subtractDays(toDateTime('{end} 00:00:00'),1)
        AND timestamp < addDays(toDateTime('{end} 00:00:00'),1) GROUP BY distinct_id)
    """
    active_sql = f"""
      SELECT uniqIf(distinct_id, toDate(timestamp)=toDate('{end}')),
        uniqIf(distinct_id, timestamp>=subtractDays(addDays(toDateTime('{end} 00:00:00'),1),7)),
        uniqIf(distinct_id, timestamp>=subtractDays(addDays(toDateTime('{end} 00:00:00'),1),30)),
        uniqIf(distinct_id, properties.$is_first_day=true)
      FROM events WHERE timestamp>=subtractDays(addDays(toDateTime('{end} 00:00:00'),1),30)
        AND timestamp<addDays(toDateTime('{end} 00:00:00'),1)
    """
    try:
        total_rows = _query(project, key, host, totals_sql, transport)
        row = total_rows[0] if total_rows else [0] * 12
        totals = dict(zip(("events", "visitors", "sessions", "pageviews",
                           "prediction_viewers", "rollover_users", "builder_users", "slip_generators",
                           "valid_code_viewers", "unique_code_copiers", "sportybet_openers",
                           "schema_validation_errors"),
                          [int(value or 0) for value in row]))
        totals["total_copy_actions"] = totals["unique_code_copiers"]
        totals["sportybet_opened"] = totals["sportybet_openers"]
        daily_rows = _query(project, key, host, daily_sql, transport)
        data = {
            "totals": totals,
            "daily": [{"date": str(r[0]), "visitors": int(r[1] or 0),
                       "sessions": int(r[2] or 0), "events": int(r[3] or 0),
                       "builds": int(r[4] or 0), "copy_actions": int(r[5] or 0)}
                      for r in daily_rows],
            "by_country": _dimension(_query(project, key, host,
                dim_sql("properties.$geoip_country_code"), transport)),
            "by_device": _dimension(_query(project, key, host,
                dim_sql("properties.$device_type"), transport)),
            "by_browser": _dimension(_query(project, key, host,
                dim_sql("properties.$browser"), transport)),
            "by_os": _dimension(_query(project, key, host,
                dim_sql("properties.$os"), transport)),
            "by_region": _dimension(_query(project, key, host,
                dim_sql("properties.$geoip_subdivision_1_name"), transport)),
            "by_source": _dimension(_query(project, key, host,
                dim_sql("coalesce(properties.$utm_source, properties.$referring_domain)"), transport)),
            "by_campaign": _dimension(_query(project, key, host,
                dim_sql("properties.$utm_campaign"), transport)),
            "by_path": _dimension(_query(project, key, host,
                dim_sql("properties.$pathname"), transport)),
        }
        funnel_specs = {
            "prediction": (["$pageview", "prediction_viewed", "booking_code_viewed",
                            "booking_code_copied", "sportybet_opened"],
                           ["Visitors", "Predictions viewed", "Valid code displayed",
                            "Code copied", "SportyBet opened"]),
            "builder": (["builder_opened", "builder_target_selected",
                         "builder_generate_requested", "booking_code_viewed",
                         "booking_code_copied", "sportybet_opened"],
                        ["Builder opened", "Target selected", "Generation requested",
                         "Valid code displayed", "Code copied", "SportyBet opened"]),
            "rollover": (["rollover_viewed", "booking_code_viewed",
                          "booking_code_copied", "sportybet_opened"],
                         ["Rollover viewed", "Valid code displayed",
                          "Code copied", "SportyBet opened"]),
        }
        data["funnels"] = {name: _funnel(
            _query(project, key, host, funnel_sql(events), transport), labels)
            for name, (events, labels) in funnel_specs.items()}
        rr = _query(project, key, host, retention_sql, transport)
        values = rr[0] if rr else [0] * 10
        data["retention"] = {}
        for index, day in enumerate((1, 3, 7, 14, 30)):
            eligible, returned = int(values[index * 2] or 0), int(values[index * 2 + 1] or 0)
            data["retention"][f"d{day}"] = {
                "eligible": eligible, "returned": returned,
                "rate": round(returned / eligible, 4) if eligible else None}
        pr = _query(project, key, host, prediction_return_sql, transport)
        eligible, returned = ([int(value or 0) for value in pr[0]] if pr else [0, 0])
        data["prediction_day_return"] = {
            "eligible": eligible, "returned": min(returned, eligible),
            "rate": round(min(returned, eligible) / eligible, 4) if eligible else None}
        ar = _query(project, key, host, active_sql, transport)
        av = [int(value or 0) for value in (ar[0] if ar else [0, 0, 0, 0])]
        data["active_users"] = {"dau": av[0], "wau": av[1], "mau": av[2]}
        data["totals"]["new_visitors"] = av[3]
        data["totals"]["returning_visitors"] = max(0, data["totals"]["visitors"] - av[3])
        as_of = datetime.now(timezone.utc)
        _write_cache(cache_key, data, as_of)
        result = {"data": data, "meta": _meta("fresh", as_of)}
        _memory[cache_key] = (now_mono, result)
        return result
    except Exception as exc:
        return {"data": persisted or {},
                "meta": _meta("stale" if persisted else "unavailable", persisted_at,
                              f"query_failed:{type(exc).__name__}")}
