"""ETL pipeline: fetch → transform → upsert into PostgreSQL/SQLite."""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from urbanpulse.ingestion.openaq_client import (
    PARAMETERS_OF_INTEREST,
    TARGET_CITIES,
    fetch_locations_by_bbox,
    fetch_measurements,
    fetch_parameters,
)
from urbanpulse.models.dimensions import DimCountry, DimLocation, DimParameter, WHO_GUIDELINES
from urbanpulse.models.facts import FactMeasurement

logger = logging.getLogger(__name__)


async def seed_parameters(session: AsyncSession) -> dict[str, int]:
    """Seed dim_parameter with WHO-standard pollutant definitions.

    Returns mapping: openaq_name → parameter_id
    """
    name_to_id: dict[str, int] = {}
    openaq_params = await fetch_parameters()

    # Merge OpenAQ API data with our WHO guidelines
    for p in openaq_params:
        name = p.get("name", "").lower()
        if name not in PARAMETERS_OF_INTEREST:
            continue
        who = WHO_GUIDELINES.get(name, {})
        stmt = select(DimParameter).where(DimParameter.openaq_id == p["id"])
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing is None:
            param = DimParameter(
                openaq_id=p["id"],
                name=name,
                display_name=who.get("display") or p.get("displayName", name),
                description=p.get("description"),
                unit=p.get("units", who.get("unit", "µg/m³")),
                who_annual_guideline=who.get("annual"),
                who_24h_guideline=who.get("daily"),
            )
            session.add(param)
            await session.flush()
            name_to_id[name] = param.parameter_id
        else:
            name_to_id[name] = existing.parameter_id

    # Fallback: if API returned nothing, seed from our constants
    if not name_to_id:
        logger.warning("OpenAQ parameters API returned no results — using fallback seed data")
        for i, (name, who) in enumerate(WHO_GUIDELINES.items(), start=1):
            stmt = select(DimParameter).where(DimParameter.name == name)
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()
            if existing is None:
                param = DimParameter(
                    openaq_id=9000 + i,
                    name=name,
                    display_name=who["display"],
                    unit=who["unit"],
                    who_annual_guideline=who.get("annual"),
                    who_24h_guideline=who.get("daily"),
                )
                session.add(param)
                await session.flush()
                name_to_id[name] = param.parameter_id
            else:
                name_to_id[name] = existing.parameter_id

    await session.commit()
    logger.info("Parameters seeded: %d", len(name_to_id))
    return name_to_id


async def seed_locations(session: AsyncSession) -> dict[int, int]:
    """Discover and upsert monitoring stations for all target cities.

    Returns mapping: openaq_location_id → location_id (DB primary key)
    """
    openaq_to_db: dict[int, int] = {}

    for city_info in TARGET_CITIES:
        stations = await fetch_locations_by_bbox(city_info["lat"], city_info["lon"], radius_km=30)
        if not stations:
            logger.warning("No stations found near %s", city_info["city"])
            continue

        for station in stations[:5]:  # max 5 stations per city
            openaq_id = station.get("id")
            if openaq_id is None:
                continue

            stmt = select(DimLocation).where(DimLocation.openaq_id == openaq_id)
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            country_id = await _ensure_country(session, station.get("country", {}).get("code", "DE"))

            coords = station.get("coordinates") or {}
            if existing is None:
                loc = DimLocation(
                    openaq_id=openaq_id,
                    name=station.get("name", f"Station {openaq_id}"),
                    city=city_info["city"],
                    country_id=country_id,
                    latitude=coords.get("latitude"),
                    longitude=coords.get("longitude"),
                    is_mobile=station.get("isMobile", False),
                    is_monitor=station.get("isMonitor", True),
                    owner_name=(station.get("owner") or {}).get("name"),
                    provider_name=(station.get("provider") or {}).get("name"),
                )
                session.add(loc)
                await session.flush()
                openaq_to_db[openaq_id] = loc.location_id
            else:
                # Update last_updated
                existing.last_updated = datetime.now(timezone.utc)
                openaq_to_db[openaq_id] = existing.location_id

    await session.commit()
    logger.info("Locations seeded/updated: %d stations", len(openaq_to_db))
    return openaq_to_db


async def ingest_recent_measurements(
    session: AsyncSession,
    openaq_to_db: dict[int, int],
    param_name_to_id: dict[str, int],
    hours_back: int = 48,
) -> int:
    """Fetch measurements for the last `hours_back` hours and upsert into DB.

    Returns total measurements inserted.
    """
    date_to = datetime.now(timezone.utc)
    date_from = date_to - timedelta(hours=hours_back)
    total = 0

    for openaq_loc_id, db_loc_id in openaq_to_db.items():
        raw = await fetch_measurements(openaq_loc_id, date_from, date_to)
        if not raw:
            continue

        rows_to_insert = []
        for m in raw:
            param_name = (m.get("parameter") or "").lower()
            param_id = param_name_to_id.get(param_name)
            if param_id is None:
                continue

            value = m.get("value")
            if value is None or value < 0:
                continue

            measured_at_str = m.get("date", {}).get("utc") or m.get("date", {}).get("local")
            if not measured_at_str:
                continue
            try:
                measured_at = datetime.fromisoformat(measured_at_str.replace("Z", "+00:00"))
            except ValueError:
                continue

            rows_to_insert.append({
                "location_id": db_loc_id,
                "parameter_id": param_id,
                "measured_at": measured_at,
                "value": float(value),
                "unit": m.get("unit"),
            })

        if not rows_to_insert:
            continue

        # Upsert: ignore conflicts (same location + parameter + timestamp)
        for row in rows_to_insert:
            stmt = select(FactMeasurement).where(
                FactMeasurement.location_id == row["location_id"],
                FactMeasurement.parameter_id == row["parameter_id"],
                FactMeasurement.measured_at == row["measured_at"],
            )
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if existing is None:
                session.add(FactMeasurement(**row))
                total += 1

        await session.commit()
        logger.debug("Ingested %d measurements for location %d", len(rows_to_insert), openaq_loc_id)

    logger.info("Ingestion complete: %d new measurements inserted", total)
    return total


async def _ensure_country(session: AsyncSession, iso_code: str) -> int | None:
    """Get or create a dim_country row. Returns country_id."""
    stmt = select(DimCountry).where(DimCountry.iso_code == iso_code.upper())
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()
    if existing:
        return existing.country_id

    country_names = {
        "DE": ("Germany", "Europe"), "FR": ("France", "Europe"), "GB": ("United Kingdom", "Europe"),
        "NL": ("Netherlands", "Europe"), "AT": ("Austria", "Europe"), "PL": ("Poland", "Europe"),
        "CZ": ("Czech Republic", "Europe"), "BE": ("Belgium", "Europe"), "CH": ("Switzerland", "Europe"),
        "IT": ("Italy", "Europe"), "ES": ("Spain", "Europe"), "SE": ("Sweden", "Europe"),
        "NO": ("Norway", "Europe"), "DK": ("Denmark", "Europe"), "FI": ("Finland", "Europe"),
    }
    name, continent = country_names.get(iso_code.upper(), (iso_code, "Europe"))
    country = DimCountry(iso_code=iso_code.upper(), name=name, continent=continent)
    session.add(country)
    await session.flush()
    return country.country_id
