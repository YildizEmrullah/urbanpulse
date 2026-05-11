"""Thin httpx wrapper for calling the FastAPI backend from Streamlit."""

import os
import httpx

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000/api/v1")
TIMEOUT = 15


def _get(path: str, params: dict | None = None) -> dict:
    try:
        with httpx.Client(base_url=API_BASE, timeout=TIMEOUT) as client:
            r = client.get(path, params=params)
            r.raise_for_status()
            return r.json()
    except Exception as exc:
        return {"error": str(exc)}


def get_locations(city: str | None = None, country_iso: str | None = None) -> dict:
    params = {}
    if city:
        params["city"] = city
    if country_iso:
        params["country_iso"] = country_iso
    return _get("/locations", params)


def get_measurements(location_id: int, parameter: str, date_from=None, date_to=None, aggregation="hourly") -> dict:
    params = {"location_id": location_id, "parameter": parameter, "aggregation": aggregation}
    if date_from:
        params["date_from"] = date_from.isoformat()
    if date_to:
        params["date_to"] = date_to.isoformat()
    return _get("/measurements", params)


def get_health_ranking() -> dict:
    return _get("/health-index/ranking")


def get_health_index(city: str) -> dict:
    return _get("/health-index", {"city": city})


def get_anomalies(severity=None, date_from=None, date_to=None) -> dict:
    params = {"limit": 200}
    if severity:
        params["severity"] = severity
    if date_from:
        params["date_from"] = date_from.isoformat()
    if date_to:
        params["date_to"] = date_to.isoformat()
    return _get("/anomalies", params)


def get_anomaly_summary() -> dict:
    return _get("/anomalies/summary")


def get_predictions(location_id: int, parameter: str) -> dict:
    return _get(f"/predictions/{location_id}/{parameter}")


def get_api_health() -> dict:
    try:
        with httpx.Client(timeout=5) as client:
            r = client.get(API_BASE.replace("/api/v1", "/health"))
            return r.json()
    except Exception as exc:
        return {"status": "offline", "error": str(exc)}
