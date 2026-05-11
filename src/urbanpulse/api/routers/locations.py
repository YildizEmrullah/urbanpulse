"""Locations router: monitoring station metadata and search."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from urbanpulse.api.dependencies import db, paginate
from urbanpulse.models.dimensions import DimCountry, DimLocation
from urbanpulse.models.facts import FactMeasurement
from urbanpulse.worker.cache import cache_get, cache_set

router = APIRouter(prefix="/locations", tags=["Locations"])


@router.get("")
async def list_locations(
    city: str | None = Query(default=None),
    country_iso: str | None = Query(default=None),
    pagination: dict = Depends(paginate),
    session: AsyncSession = Depends(db),
):
    """List monitoring stations with optional city/country filter."""
    cache_key = f"locations:{city}:{country_iso}:{pagination}"
    cached = await cache_get(cache_key)
    if cached:
        return cached

    stmt = select(DimLocation)
    if city:
        stmt = stmt.where(func.lower(DimLocation.city) == city.lower())
    if country_iso:
        stmt = stmt.join(DimCountry).where(DimCountry.iso_code == country_iso.upper())
    stmt = stmt.offset(pagination["offset"]).limit(pagination["limit"])
    result = await session.execute(stmt)
    locs = result.scalars().all()

    data = [
        {
            "location_id": l.location_id,
            "openaq_id": l.openaq_id,
            "name": l.name,
            "city": l.city,
            "country_id": l.country_id,
            "latitude": float(l.latitude) if l.latitude else None,
            "longitude": float(l.longitude) if l.longitude else None,
            "is_mobile": l.is_mobile,
            "owner_name": l.owner_name,
        }
        for l in locs
    ]
    response = {"total": len(data), "results": data}
    await cache_set(cache_key, response)
    return response


@router.get("/{location_id}")
async def get_location(location_id: int, session: AsyncSession = Depends(db)):
    """Get a single monitoring station with its latest measurements."""
    stmt = select(DimLocation).where(DimLocation.location_id == location_id)
    loc = (await session.execute(stmt)).scalar_one_or_none()
    if loc is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Location not found")

    # Latest measurement per parameter
    latest_stmt = select(FactMeasurement).where(
        FactMeasurement.location_id == location_id
    ).order_by(FactMeasurement.measured_at.desc()).limit(20)
    measurements = (await session.execute(latest_stmt)).scalars().all()

    return {
        "location_id": loc.location_id,
        "openaq_id": loc.openaq_id,
        "name": loc.name,
        "city": loc.city,
        "latitude": float(loc.latitude) if loc.latitude else None,
        "longitude": float(loc.longitude) if loc.longitude else None,
        "is_mobile": loc.is_mobile,
        "latest_measurements": [
            {
                "parameter_id": m.parameter_id,
                "measured_at": m.measured_at.isoformat(),
                "value": float(m.value),
                "unit": m.unit,
            }
            for m in measurements
        ],
    }
