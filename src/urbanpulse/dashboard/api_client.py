"""Thin httpx wrapper for calling the FastAPI backend from Streamlit.

Falls back to direct SQLite queries when the API is unavailable (e.g. Streamlit Cloud).
"""

import os
import sqlite3
from pathlib import Path

import httpx

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000/api/v1")
TIMEOUT = 15


# ── HTTP client ───────────────────────────────────────────────────────────────

def _get(path: str, params: dict | None = None) -> dict:
    try:
        with httpx.Client(base_url=API_BASE, timeout=TIMEOUT) as client:
            r = client.get(path, params=params)
            r.raise_for_status()
            return r.json()
    except Exception:
        return {"error": "api_unavailable"}


# ── SQLite direct fallback ────────────────────────────────────────────────────

def _db_path() -> str:
    """Find urbanpulse.db: env var → walk up from this file → CWD."""
    db_url = os.getenv("DATABASE_URL", "")
    if "sqlite" in db_url:
        return db_url.split("///")[-1]
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "urbanpulse.db"
        if candidate.exists():
            return str(candidate)
    return "urbanpulse.db"


def _sql(query: str, params: tuple = ()) -> list[dict]:
    try:
        conn = sqlite3.connect(_db_path())
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute(query, params).fetchall()]
        conn.close()
        return rows
    except Exception:
        return []


def _caqi(pm25, pm10, no2, o3) -> dict:
    """Minimal EU CAQI calculation."""
    def sub(val, breaks):
        if val is None:
            return None
        lo_c, hi_c = [(breaks[i], breaks[i+1]) for i in range(len(breaks)-1)
                      if breaks[i] <= val < breaks[i+1]][0] if val < breaks[-1] else [(breaks[-2], breaks[-1])]
        lo_i, hi_i = i * 25, (i + 1) * 25 if (i := next(
            (j for j in range(len(breaks)-1) if breaks[j] <= val < breaks[j+1]), len(breaks)-2
        )) < 4 else 100
        return round(lo_i + (val - breaks[lo_i // 25 if lo_i < 100 else -2]) /
                     ((breaks[lo_i // 25 + 1 if lo_i < 100 else -1] - breaks[lo_i // 25 if lo_i < 100 else -2]) or 1) * 25, 1)

    breaks = {
        "pm25": [0, 15, 30, 55, 110],
        "pm10": [0, 25, 50, 90, 180],
        "no2":  [0, 50, 100, 200, 400],
        "o3":   [0, 60, 120, 180, 240],
    }
    subs = {k: None for k in breaks}
    for k, v in zip(breaks, [pm25, pm10, no2, o3]):
        if v is None:
            continue
        bp = breaks[k]
        idx = next((i for i in range(len(bp)-1) if bp[i] <= v < bp[i+1]), len(bp)-2)
        lo_i, hi_i = idx * 25, min((idx + 1) * 25, 100)
        subs[k] = round(lo_i + (v - bp[idx]) / ((bp[idx+1] - bp[idx]) or 1) * (hi_i - lo_i), 1)

    valid = [s for s in subs.values() if s is not None]
    score = max(valid) if valid else 0
    bands = [(0,25,"Very Low","#79BC6A","Air quality is good."),
             (25,50,"Low","#BBCF4C","Air quality is acceptable."),
             (50,75,"Medium","#EEC20B","Sensitive groups may be affected."),
             (75,100,"High","#F29305","Everyone may begin to experience health effects."),
             (100,999,"Very High","#E8416F","Health warnings of emergency conditions.")]
    band, color, msg = next(((b, c, m) for lo, hi, b, c, m in bands if lo <= score < hi),
                            ("Very High", "#E8416F", "Health warnings of emergency conditions."))
    return {"caqi": round(score, 1), "band": band, "color": color, "message": msg,
            "sub_indices": {"pm25": subs["pm25"], "pm10": subs["pm10"],
                            "no2": subs["no2"], "o3": subs["o3"]}}


# ── Public API (HTTP-first, SQLite fallback) ──────────────────────────────────

def get_locations(city: str | None = None, country_iso: str | None = None) -> dict:
    params = {}
    if city:
        params["city"] = city
    if country_iso:
        params["country_iso"] = country_iso
    result = _get("/locations", params)
    if "error" not in result:
        return result

    where, args = "WHERE 1=1", []
    if city:
        where += " AND lower(city) = lower(?)"; args.append(city)
    if country_iso:
        where += " AND country_iso = ?"; args.append(country_iso.upper())
    rows = _sql(f"""
        SELECT l.location_id, l.name, l.city, l.latitude, l.longitude,
               l.is_mobile, l.is_monitor, c.iso_code AS country_iso
        FROM dim_location l
        LEFT JOIN dim_country c ON c.country_id = l.country_id
        {where}
        ORDER BY l.city, l.name
        LIMIT 200
    """, tuple(args))
    return {"locations": rows, "count": len(rows)}


def get_measurements(location_id: int, parameter: str, date_from=None, date_to=None,
                     aggregation="hourly") -> dict:
    params = {"location_id": location_id, "parameter": parameter, "aggregation": aggregation}
    if date_from:
        params["date_from"] = date_from.isoformat()
    if date_to:
        params["date_to"] = date_to.isoformat()
    result = _get("/measurements", params)
    if "error" not in result:
        return result

    from_str = date_from.strftime("%Y-%m-%d %H:%M:%S") if date_from else "2000-01-01 00:00:00"
    to_str = date_to.strftime("%Y-%m-%d %H:%M:%S") if date_to else "2099-12-31 23:59:59"

    if aggregation == "raw":
        rows = _sql("""
            SELECT fm.measured_at, fm.value, fm.unit
            FROM fact_measurement fm
            JOIN dim_parameter p ON p.parameter_id = fm.parameter_id
            WHERE fm.location_id = ? AND lower(p.name) = lower(?)
              AND fm.measured_at BETWEEN ? AND ?
            ORDER BY fm.measured_at LIMIT 1000
        """, (location_id, parameter, from_str, to_str))
        data = [{"measured_at": r["measured_at"], "value": round(float(r["value"]), 3),
                 "unit": r["unit"]} for r in rows]
    else:
        trunc = "strftime('%Y-%m-%d %H:00:00', measured_at)" if aggregation == "hourly" else "date(measured_at)"
        rows = _sql(f"""
            SELECT {trunc} AS bucket,
                   AVG(fm.value) AS avg_value, MAX(fm.value) AS max_value,
                   MIN(fm.value) AS min_value, COUNT(*) AS n
            FROM fact_measurement fm
            JOIN dim_parameter p ON p.parameter_id = fm.parameter_id
            WHERE fm.location_id = ? AND lower(p.name) = lower(?)
              AND fm.measured_at BETWEEN ? AND ?
            GROUP BY bucket ORDER BY bucket LIMIT 500
        """, (location_id, parameter, from_str, to_str))
        data = [{"bucket": r["bucket"], "avg": round(r["avg_value"], 3),
                 "max": round(r["max_value"], 3), "min": round(r["min_value"], 3),
                 "n": r["n"]} for r in rows]

    who = _sql("SELECT who_24h_guideline FROM dim_parameter WHERE lower(name)=lower(?) LIMIT 1",
               (parameter,))
    return {"location_id": location_id, "parameter": parameter, "aggregation": aggregation,
            "who_24h_guideline": who[0]["who_24h_guideline"] if who else None,
            "count": len(data), "results": data}


def get_health_ranking() -> dict:
    result = _get("/health-index/ranking")
    if "error" not in result:
        return result

    rows = _sql("""
        SELECT l.city, p.name AS param, AVG(fm.value) AS avg_val
        FROM fact_measurement fm
        JOIN dim_location l ON l.location_id = fm.location_id
        JOIN dim_parameter p ON p.parameter_id = fm.parameter_id
        WHERE fm.measured_at >= datetime('now', '-48 hours')
          AND l.city IS NOT NULL
        GROUP BY l.city, p.name ORDER BY l.city
    """)
    city_params: dict[str, dict] = {}
    for r in rows:
        city_params.setdefault(r["city"], {})[r["param"]] = r["avg_val"]

    from datetime import datetime, timezone
    ranking = []
    for city, params in city_params.items():
        c = _caqi(params.get("pm25"), params.get("pm10"),
                  params.get("no2"), params.get("o3"))
        ranking.append({"city": city, "caqi": c["caqi"], "band": c["band"], "color": c["color"]})
    ranking.sort(key=lambda x: x["caqi"])
    return {"ranking": ranking, "computed_at": datetime.now(timezone.utc).isoformat()}


def get_health_index(city: str) -> dict:
    result = _get("/health-index", {"city": city})
    if "error" not in result:
        return result

    rows = _sql("""
        SELECT p.name AS param, AVG(fm.value) AS avg_val
        FROM fact_measurement fm
        JOIN dim_location l ON l.location_id = fm.location_id
        JOIN dim_parameter p ON p.parameter_id = fm.parameter_id
        WHERE lower(l.city) = lower(?) AND fm.measured_at >= datetime('now', '-48 hours')
        GROUP BY p.name
    """, (city,))
    params = {r["param"]: r["avg_val"] for r in rows}
    c = _caqi(params.get("pm25"), params.get("pm10"), params.get("no2"), params.get("o3"))
    from datetime import datetime, timezone
    return {"city": city, **c, "raw_concentrations": params,
            "computed_at": datetime.now(timezone.utc).isoformat()}


def get_anomalies(severity=None, date_from=None, date_to=None) -> dict:
    params: dict = {"limit": 200}
    if severity:
        params["severity"] = severity
    if date_from:
        params["date_from"] = date_from.isoformat()
    if date_to:
        params["date_to"] = date_to.isoformat()
    result = _get("/anomalies", params)
    if "error" not in result:
        return result

    where, args = "WHERE 1=1", []
    if severity:
        where += " AND e.severity = ?"; args.append(severity)
    rows = _sql(f"""
        SELECT e.event_id, l.city, l.name AS station, p.name AS parameter,
               e.measured_value, e.expected_value, e.severity, e.detected_at
        FROM fact_anomaly_event e
        JOIN dim_location l ON l.location_id = e.location_id
        JOIN dim_parameter p ON p.parameter_id = e.parameter_id
        {where}
        ORDER BY e.detected_at DESC LIMIT 200
    """, tuple(args))
    return {"anomalies": rows, "count": len(rows)}


def get_anomaly_summary() -> dict:
    result = _get("/anomalies/summary")
    if "error" not in result:
        return result
    rows = _sql("""
        SELECT severity, COUNT(*) AS count
        FROM fact_anomaly_event GROUP BY severity
    """)
    return {"by_severity": {r["severity"]: r["count"] for r in rows}}


def get_predictions(location_id: int, parameter: str) -> dict:
    result = _get(f"/predictions/{location_id}/{parameter}")
    if "error" not in result:
        return result

    rows = _sql("""
        SELECT pr.forecast_horizon_hours, pr.predicted_value, pr.confidence_lower,
               pr.confidence_upper, pr.predicted_at
        FROM fact_ml_prediction pr
        JOIN dim_parameter p ON p.parameter_id = pr.parameter_id
        WHERE pr.location_id = ? AND lower(p.name) = lower(?)
        ORDER BY pr.predicted_at DESC, pr.forecast_horizon_hours
        LIMIT 48
    """, (location_id, parameter))
    return {"location_id": location_id, "parameter": parameter, "predictions": rows}


def get_api_health() -> dict:
    try:
        with httpx.Client(timeout=5) as client:
            r = client.get(API_BASE.replace("/api/v1", "/health"))
            return r.json()
    except Exception:
        return {"status": "ok", "mode": "direct-sqlite"}
