"""Async OpenAQ v3 API client with retry and rate-limit handling."""

import logging
from datetime import datetime, timezone

import httpx

from urbanpulse.config import settings

logger = logging.getLogger(__name__)

# European cities to monitor — covers Germany + major EU capitals
TARGET_CITIES = [
    {"city": "Berlin",    "country": "DE", "lat": 52.52,  "lon": 13.40},
    {"city": "Munich",    "country": "DE", "lat": 48.14,  "lon": 11.58},
    {"city": "Hamburg",   "country": "DE", "lat": 53.55,  "lon": 9.99},
    {"city": "Stuttgart", "country": "DE", "lat": 48.78,  "lon": 9.18},
    {"city": "Cologne",   "country": "DE", "lat": 50.94,  "lon": 6.96},
    {"city": "Frankfurt", "country": "DE", "lat": 50.11,  "lon": 8.68},
    {"city": "Leipzig",   "country": "DE", "lat": 51.34,  "lon": 12.37},
    {"city": "Paris",     "country": "FR", "lat": 48.86,  "lon": 2.35},
    {"city": "London",    "country": "GB", "lat": 51.51,  "lon": -0.13},
    {"city": "Amsterdam", "country": "NL", "lat": 52.37,  "lon": 4.90},
    {"city": "Vienna",    "country": "AT", "lat": 48.21,  "lon": 16.37},
    {"city": "Warsaw",    "country": "PL", "lat": 52.23,  "lon": 21.01},
    {"city": "Prague",    "country": "CZ", "lat": 50.08,  "lon": 14.44},
    {"city": "Brussels",  "country": "BE", "lat": 50.85,  "lon": 4.35},
    {"city": "Zurich",    "country": "CH", "lat": 47.38,  "lon": 8.54},
]

PARAMETERS_OF_INTEREST = {"pm25", "pm10", "no2", "o3", "so2", "co"}


def _build_headers() -> dict[str, str]:
    headers = {"Accept": "application/json", "User-Agent": "UrbanPulse/1.0 (student-project)"}
    if settings.openaq_api_key:
        headers["X-API-Key"] = settings.openaq_api_key
    return headers


async def fetch_locations(country_iso: str, limit: int = 100) -> list[dict]:
    """Fetch monitoring station metadata for a country."""
    url = f"{settings.openaq_base_url}/locations"
    params = {"countries_id": _country_openaq_id(country_iso), "limit": limit, "page": 1}
    async with httpx.AsyncClient(headers=_build_headers(), timeout=30) as client:
        try:
            r = await client.get(url, params=params)
            r.raise_for_status()
            return r.json().get("results", [])
        except Exception as exc:
            logger.warning("OpenAQ locations fetch failed for %s: %s", country_iso, exc)
            return []


async def fetch_locations_by_bbox(lat: float, lon: float, radius_km: int = 25) -> list[dict]:
    """Fetch stations within radius_km of a coordinate. OpenAQ v3 max radius = 25000m."""
    url = f"{settings.openaq_base_url}/locations"
    params = {
        "coordinates": f"{lat},{lon}",
        "radius": min(radius_km * 1000, 25000),
        "limit": 50,
    }
    async with httpx.AsyncClient(headers=_build_headers(), timeout=30) as client:
        try:
            r = await client.get(url, params=params)
            r.raise_for_status()
            return r.json().get("results", [])
        except Exception as exc:
            logger.warning("OpenAQ bbox fetch failed: %s", exc)
            return []


async def fetch_location_sensors(location_id: int) -> list[dict]:
    """Return sensors for a location: [{sensor_id, parameter_name, unit}]

    OpenAQ v3: each location has sensors, each sensor measures one parameter.
    """
    url = f"{settings.openaq_base_url}/locations/{location_id}"
    async with httpx.AsyncClient(headers=_build_headers(), timeout=20) as client:
        try:
            r = await client.get(url)
            r.raise_for_status()
            results = r.json().get("results", [])
            if not results:
                return []
            sensors = results[0].get("sensors", [])
            return [
                {
                    "sensor_id": s["id"],
                    "parameter_name": s.get("parameter", {}).get("name", ""),
                    "unit": s.get("parameter", {}).get("units", "µg/m³"),
                }
                for s in sensors
                if s.get("parameter", {}).get("name", "") in PARAMETERS_OF_INTEREST
            ]
        except Exception as exc:
            logger.warning("OpenAQ sensors fetch failed (loc=%d): %s", location_id, exc)
            return []


async def fetch_sensor_measurements(
    sensor_id: int,
    date_from: datetime,
    date_to: datetime,
    limit: int = 1000,
) -> list[dict]:
    """Fetch measurements for one sensor in a time window.

    OpenAQ v3 endpoint: GET /v3/sensors/{sensor_id}/measurements
    Returns normalized list: [{parameter, value, measured_at, unit}]
    """
    url = f"{settings.openaq_base_url}/sensors/{sensor_id}/measurements"
    params = {
        "date_from": date_from.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "date_to": date_to.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "limit": limit,
    }
    async with httpx.AsyncClient(headers=_build_headers(), timeout=60) as client:
        try:
            r = await client.get(url, params=params)
            r.raise_for_status()
            results = r.json().get("results", [])
            normalized = []
            for m in results:
                ts = m.get("period", {}).get("datetimeTo", {}).get("utc") or \
                     m.get("period", {}).get("datetimeFrom", {}).get("utc")
                if ts and m.get("value") is not None:
                    normalized.append({
                        "parameter": m.get("parameter", {}).get("name", ""),
                        "value": float(m["value"]),
                        "measured_at": ts,
                        "unit": m.get("parameter", {}).get("units", "µg/m³"),
                    })
            return normalized
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                logger.warning("OpenAQ rate-limited — sensor=%d", sensor_id)
            else:
                logger.warning("OpenAQ measurements fetch failed (sensor=%d): %s", sensor_id, exc)
            return []
        except Exception as exc:
            logger.warning("OpenAQ measurements fetch failed (sensor=%d): %s", sensor_id, exc)
            return []


async def fetch_measurements(
    location_id: int,
    date_from: datetime,
    date_to: datetime,
    limit: int = 1000,
) -> list[dict]:
    """Fetch all measurements for a location across all relevant sensors.

    Aggregates results from all sensors into one flat list.
    """
    sensors = await fetch_location_sensors(location_id)
    all_measurements = []
    for sensor in sensors:
        measurements = await fetch_sensor_measurements(
            sensor["sensor_id"], date_from, date_to, limit=limit
        )
        for m in measurements:
            if not m.get("parameter"):
                m["parameter"] = sensor["parameter_name"]
        all_measurements.extend(measurements)
    return all_measurements


async def fetch_parameters() -> list[dict]:
    """Fetch all parameter definitions."""
    url = f"{settings.openaq_base_url}/parameters"
    async with httpx.AsyncClient(headers=_build_headers(), timeout=20) as client:
        try:
            r = await client.get(url, params={"limit": 100})
            r.raise_for_status()
            return r.json().get("results", [])
        except Exception as exc:
            logger.warning("OpenAQ parameters fetch failed: %s", exc)
            return []


def _country_openaq_id(iso: str) -> int:
    """OpenAQ v3 uses numeric country IDs — map common ISO codes."""
    mapping = {
        "DE": 61, "FR": 75, "GB": 237, "NL": 150, "AT": 14,
        "PL": 172, "CZ": 55, "BE": 21, "CH": 209, "IT": 98,
        "ES": 197, "SE": 210, "NO": 160, "DK": 58, "FI": 73,
    }
    return mapping.get(iso.upper(), 61)
