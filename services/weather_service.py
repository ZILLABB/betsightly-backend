"""WeatherAPI forecast client for BetSightly match context.

Weather remains SHADOW ONLY. Nothing here changes prediction confidence,
trust, selection probability, market eligibility, or SportyBet bookability.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

API_KEY = os.getenv("WEATHERAPI_KEY", "")
BASE_URL = "https://api.weatherapi.com/v1"
CACHE_DIR = Path("cache/weatherapi")

# WeatherAPI permits forecast caching up to 24h. Six hours also lines up
# with normal forecast refresh cadence and keeps context reasonably fresh.
FORECAST_CACHE_TTL = timedelta(hours=6)

# Free WeatherAPI accounts expose a 3-day forecast.
FREE_FORECAST_DAYS = 3


class WeatherAPIService:
    def __init__(
        self,
        api_key: str | None = None,
    ):
        self.api_key = api_key or API_KEY
        self.timeout = 20

        CACHE_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

    def _cache_path(
        self,
        location: str,
        days: int,
    ) -> Path:
        raw = (
            f"{location.casefold()}:{days}"
        )

        digest = hashlib.sha256(
            raw.encode("utf-8")
        ).hexdigest()

        return CACHE_DIR / f"{digest}.json"

    def _read_cache(
        self,
        location: str,
        days: int,
    ) -> dict | None:
        path = self._cache_path(
            location,
            days,
        )

        if not path.exists():
            return None

        try:
            data = json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )

            cached_at = datetime.fromisoformat(
                data["cached_at"]
            )

            if cached_at.tzinfo is None:
                cached_at = cached_at.replace(
                    tzinfo=timezone.utc
                )

            if (
                datetime.now(timezone.utc)
                - cached_at.astimezone(
                    timezone.utc
                )
                > FORECAST_CACHE_TTL
            ):
                return None

            return data.get("payload")

        except Exception:
            return None

    def _write_cache(
        self,
        location: str,
        days: int,
        payload: dict,
    ) -> None:
        try:
            self._cache_path(
                location,
                days,
            ).write_text(
                json.dumps(
                    {
                        "cached_at": datetime.now(
                            timezone.utc
                        ).isoformat(),
                        "payload": payload,
                    },
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )

        except Exception as exc:
            logger.debug(
                "Weather cache write failed: %s",
                exc,
            )

    def forecast(
        self,
        location: str,
        *,
        days: int = FREE_FORECAST_DAYS,
    ) -> dict:
        location = str(
            location or ""
        ).strip()

        if not location:
            return {
                "status": "UNKNOWN",
                "reason": "missing_location",
            }

        if not self.api_key:
            return {
                "status": "UNKNOWN",
                "reason": "weatherapi_key_not_configured",
            }

        days = max(
            1,
            min(
                FREE_FORECAST_DAYS,
                int(days),
            ),
        )

        cached = self._read_cache(
            location,
            days,
        )

        if cached is not None:
            return cached

        try:
            response = requests.get(
                f"{BASE_URL}/forecast.json",
                params={
                    "key": self.api_key,
                    "q": location,
                    "days": days,
                    "aqi": "no",
                    "alerts": "no",
                },
                timeout=self.timeout,
            )

            response.raise_for_status()
            payload = response.json()

            self._write_cache(
                location,
                days,
                payload,
            )

            return payload

        except Exception as exc:
            logger.warning(
                "WeatherAPI forecast failed for %s: %s",
                location,
                exc,
            )

            return {
                "status": "UNKNOWN",
                "reason": (
                    f"weatherapi_{type(exc).__name__}"
                ),
            }


def _parse_kickoff(
    value: Any,
) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(
            str(value).replace(
                "Z",
                "+00:00",
            )
        )

        if parsed.tzinfo is None:
            parsed = parsed.replace(
                tzinfo=timezone.utc
            )

        return parsed.astimezone(
            timezone.utc
        )

    except (TypeError, ValueError):
        return None


def weather_at_kickoff(
    payload: dict,
    kickoff: Any,
) -> dict:
    """Choose the forecast hour nearest to the actual kickoff."""
    kickoff_dt = _parse_kickoff(
        kickoff
    )

    if kickoff_dt is None:
        return {
            "status": "UNKNOWN",
            "reason": "invalid_kickoff",
        }

    if payload.get("status") == "UNKNOWN":
        return dict(payload)

    location = payload.get(
        "location"
    ) or {}

    # Forecast hour timestamps are local to WeatherAPI's returned location.
    offset_seconds = int(
        round(
            float(
                location.get(
                    "utc_offset_seconds",
                    0,
                )
                or 0
            )
        )
    )

    # WeatherAPI does not always expose utc_offset_seconds. time_epoch is the
    # authoritative comparison when present, so no guessed timezone is needed.
    target_epoch = kickoff_dt.timestamp()

    candidates = []

    for day in (
        (
            payload.get("forecast")
            or {}
        ).get(
            "forecastday",
            [],
        )
        or []
    ):
        for hour in day.get(
            "hour",
            [],
        ) or []:
            try:
                epoch = float(
                    hour.get("time_epoch")
                )

            except (TypeError, ValueError):
                continue

            candidates.append(
                (
                    abs(
                        epoch
                        - target_epoch
                    ),
                    hour,
                )
            )

    if not candidates:
        return {
            "status": "UNKNOWN",
            "reason": "kickoff_outside_forecast_window",
        }

    candidates.sort(
        key=lambda item: item[0]
    )

    difference, hour = candidates[0]

    # Anything more than two hours away is not genuinely kickoff weather.
    if difference > 2 * 3600:
        return {
            "status": "UNKNOWN",
            "reason": "kickoff_outside_forecast_window",
        }

    condition = (
        hour.get("condition")
        or {}
    )

    return {
        "status": "AVAILABLE",
        "provider": "weatherapi",
        "forecast_time_epoch": hour.get(
            "time_epoch"
        ),
        "temperature_c": hour.get(
            "temp_c"
        ),
        "feels_like_c": hour.get(
            "feelslike_c"
        ),
        "precip_mm": hour.get(
            "precip_mm"
        ),
        "chance_of_rain": hour.get(
            "chance_of_rain"
        ),
        "chance_of_snow": hour.get(
            "chance_of_snow"
        ),
        "wind_kph": hour.get(
            "wind_kph"
        ),
        "gust_kph": hour.get(
            "gust_kph"
        ),
        "humidity": hour.get(
            "humidity"
        ),
        "condition": condition.get(
            "text"
        ),
        "condition_code": condition.get(
            "code"
        ),
    }


def get_weather_service() -> WeatherAPIService:
    return WeatherAPIService()
