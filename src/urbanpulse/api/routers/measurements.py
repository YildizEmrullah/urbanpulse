"""Measurements router: time-series queries with aggregation."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from urbanpulse.api.dependencies import db, paginate
from urbanpulse.models.dimensions import DimParameter
from urbanpulse.models.facts import FactMeasurement
from urbanpulse.worker.cache import cache_get, cache_set

router = APIRouter(prefix="/measurements", tags=["Measurements"])


@router.get("")
async def get_measurements(
    location_id: int = Query(..., description="DB location ID"),
    parameter: str = Query(..., description="Pollutant name: pm25, pm10, no2, o3, so2, co"),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    aggregation: str = Query(default="raw", pattern="^(raw|hourly|daily)$"),
    pagination: dict = Depends(paginate),
    session: AsyncSession = Depends(db),
):
    """Retrieve time-series measurements. Supports raw, hourly, and daily aggregation."""
    if date_to is None:
        date_to = datetime.now(timezone.utc)
    if date_from is None:
        date_from = date_to - timedelta(days=7)

    cache_key = f"measurements:{location_id}:{parameter}:{date_from}:{date_to}:{aggregation}"
    cached = await cache_get(cache_key)
    if cached:
        return cached

    # Resolve parameter_id — order by ID so demo data (lower IDs) takes precedence
    param_stmt = select(DimParameter).where(DimParameter.name == parameter.lower()).order_by(DimParameter.parameter_id)
    param = (await session.execute(param_stmt)).scalars().first()
    if param is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Parameter '{parameter}' not found")

    if aggregation == "raw":
        stmt = (
            select(FactMeasurement)
            .where(
                FactMeasurement.location_id == location_id,
                FactMeasurement.parameter_id == param.parameter_id,
                FactMeasurement.measured_at >= date_from,
                FactMeasurement.measured_at <= date_to,
            )
            .order_by(FactMeasurement.measured_at)
            .offset(pagination["offset"])
            .limit(pagination["limit"])
        )
        rows = (await session.execute(stmt)).scalars().all()
        data = [
            {"measured_at": r.measured_at.isoformat(), "value": float(r.value), "unit": r.unit}
            for r in rows
        ]
    else:
        trunc = "date_trunc('hour', measured_at)" if aggregation == "hourly" else "DATE(measured_at)"
        sql = text(f"""
            SELECT {trunc} AS bucket,
                   AVG(value) AS avg_value,
                   MAX(value) AS max_value,
                   MIN(value) AS min_value,
                   COUNT(*) AS n
            FROM fact_measurement
            WHERE location_id = :loc AND parameter_id = :param
              AND measured_at >= :from_ AND measured_at <= :to_
            GROUP BY bucket ORDER BY bucket
            LIMIT :limit OFFSET :offset
        """)
        result = await session.execute(sql, {
            "loc": location_id, "param": param.parameter_id,
            "from_": date_from, "to_": date_to,
            "limit": pagination["limit"], "offset": pagination["offset"],
        })
        rows = result.fetchall()
        data = [
            {"bucket": r[0], "avg": round(r[1], 3), "max": round(r[2], 3), "min": round(r[3], 3), "n": r[4]}
            for r in rows
        ]

    response = {
        "location_id": location_id,
        "parameter": parameter,
        "aggregation": aggregation,
        "who_24h_guideline": float(param.who_24h_guideline) if param.who_24h_guideline else None,
        "count": len(data),
        "results": data,
    }
    await cache_set(cache_key, response, ttl=180)
    return response


@router.get("/latest")
async def latest_measurements(
    city: str = Query(..., description="City name, e.g. Berlin"),
    parameter: str = Query(default="pm25"),
    session: AsyncSession = Depends(db),
):
    """Latest measurement value per station in a city. Cached for 5 min."""
    cache_key = f"latest:{city}:{parameter}"
    cached = await cache_get(cache_key)
    if cached:
        return cached

    sql = text("""
        SELECT l.location_id, l.name, l.city, l.latitude, l.longitude,
               m.value, m.unit, m.measured_at
        FROM dim_location l
        JOIN fact_measurement m ON m.location_id = l.location_id
        JOIN dim_parameter p ON p.parameter_id = m.parameter_id
        WHERE lower(l.city) = lower(:city) AND p.name = lower(:param)
          AND m.measured_at = (
              SELECT MAX(m2.measured_at) FROM fact_measurement m2
              WHERE m2.location_id = l.location_id AND m2.parameter_id = p.parameter_id
          )
        LIMIT 20
    """)
    result = await session.execute(sql, {"city": city, "param": parameter})
    rows = result.fetchall()
    data = [
        {
            "location_id": r[0], "name": r[1], "city": r[2],
            "latitude": r[3], "longitude": r[4],
            "value": float(r[5]) if r[5] else None,
            "unit": r[6],
            "measured_at": r[7].isoformat() if r[7] else None,
        }
        for r in rows
    ]
    response = {"city": city, "parameter": parameter, "stations": data}
    await cache_set(cache_key, response)
    return response
