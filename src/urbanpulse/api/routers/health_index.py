"""Health index router: EU CAQI computation and city ranking."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from urbanpulse.api.dependencies import db
from urbanpulse.ml.health_index import compute_caqi

router = APIRouter(prefix="/health-index", tags=["Health Index"])


@router.get("")
async def get_health_index(
    city: str = Query(..., description="City name, e.g. Berlin"),
    session: AsyncSession = Depends(db),
):
    """Compute EU CAQI for a city using the most recent measurements."""
    sql = text("""
        SELECT p.name AS param, AVG(m.value) AS avg_val
        FROM fact_measurement m
        JOIN dim_parameter p ON p.parameter_id = m.parameter_id
        JOIN dim_location l ON l.location_id = m.location_id
        WHERE lower(l.city) = lower(:city)
          AND m.measured_at >= datetime('now', '-1 hours')
        GROUP BY p.name
    """)
    result = await session.execute(sql, {"city": city})
    rows = {r[0]: r[1] for r in result.fetchall()}

    caqi = compute_caqi(
        pm25=rows.get("pm25"),
        pm10=rows.get("pm10"),
        no2=rows.get("no2"),
        o3=rows.get("o3"),
    )
    return {
        "city": city,
        "caqi": caqi.caqi,
        "band": caqi.band,
        "color": caqi.color,
        "message": caqi.message,
        "sub_indices": {
            "pm25": caqi.pm25_sub,
            "pm10": caqi.pm10_sub,
            "no2": caqi.no2_sub,
            "o3": caqi.o3_sub,
        },
        "raw_concentrations": rows,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/ranking")
async def city_ranking(session: AsyncSession = Depends(db)):
    """Rank all monitored cities by current CAQI score."""
    sql = text("""
        SELECT l.city, p.name AS param, AVG(m.value) AS avg_val
        FROM fact_measurement m
        JOIN dim_parameter p ON p.parameter_id = m.parameter_id
        JOIN dim_location l ON l.location_id = m.location_id
        WHERE m.measured_at >= datetime('now', '-2 hours')
          AND l.city IS NOT NULL
        GROUP BY l.city, p.name
        ORDER BY l.city
    """)
    result = await session.execute(sql)
    rows = result.fetchall()

    city_params: dict[str, dict] = {}
    for city, param, val in rows:
        city_params.setdefault(city, {})[param] = val

    ranking = []
    for city, params in city_params.items():
        caqi = compute_caqi(
            pm25=params.get("pm25"),
            pm10=params.get("pm10"),
            no2=params.get("no2"),
            o3=params.get("o3"),
        )
        ranking.append({
            "city": city,
            "caqi": caqi.caqi,
            "band": caqi.band,
            "color": caqi.color,
        })

    ranking.sort(key=lambda x: x["caqi"])
    return {"ranking": ranking, "computed_at": datetime.now(timezone.utc).isoformat()}
