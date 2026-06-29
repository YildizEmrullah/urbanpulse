"""
Seed the database with realistic synthetic air quality data for demo/portfolio purposes.

Usage:
    python scripts/seed_demo_data.py
"""

import asyncio
import math
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from sqlalchemy import text, insert, select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from urbanpulse.database import Base
from urbanpulse.models.dimensions import DimCountry, DimLocation, DimParameter, WHO_GUIDELINES
from urbanpulse.models.facts import FactMeasurement

random.seed(42)

CITIES = [
    {"city": "Berlin",    "country": "DE", "lat": 52.52,  "lon": 13.40},
    {"city": "Munich",    "country": "DE", "lat": 48.14,  "lon": 11.58},
    {"city": "Hamburg",   "country": "DE", "lat": 53.55,  "lon":  9.99},
    {"city": "Paris",     "country": "FR", "lat": 48.85,  "lon":  2.35},
    {"city": "London",    "country": "GB", "lat": 51.51,  "lon": -0.13},
    {"city": "Amsterdam", "country": "NL", "lat": 52.37,  "lon":  4.90},
    {"city": "Vienna",    "country": "AT", "lat": 48.21,  "lon": 16.37},
    {"city": "Warsaw",    "country": "PL", "lat": 52.23,  "lon": 21.01},
    {"city": "Prague",    "country": "CZ", "lat": 50.08,  "lon": 14.44},
    {"city": "Brussels",  "country": "BE", "lat": 50.85,  "lon":  4.35},
]

COUNTRIES = {
    "DE": "Germany", "FR": "France", "GB": "United Kingdom",
    "NL": "Netherlands", "AT": "Austria", "PL": "Poland",
    "CZ": "Czech Republic", "BE": "Belgium",
}

BASE_CONCENTRATIONS = {
    "Berlin":    {"pm25": 11, "pm10": 20, "no2": 28, "o3": 55},
    "Munich":    {"pm25":  9, "pm10": 17, "no2": 22, "o3": 62},
    "Hamburg":   {"pm25": 12, "pm10": 22, "no2": 30, "o3": 50},
    "Paris":     {"pm25": 14, "pm10": 24, "no2": 38, "o3": 48},
    "London":    {"pm25": 10, "pm10": 18, "no2": 35, "o3": 45},
    "Amsterdam": {"pm25":  8, "pm10": 15, "no2": 25, "o3": 58},
    "Vienna":    {"pm25": 13, "pm10": 21, "no2": 32, "o3": 60},
    "Warsaw":    {"pm25": 22, "pm10": 38, "no2": 28, "o3": 42},
    "Prague":    {"pm25": 18, "pm10": 30, "no2": 30, "o3": 44},
    "Brussels":  {"pm25": 13, "pm10": 22, "no2": 36, "o3": 50},
}

PARAMS = ["pm25", "pm10", "no2", "o3"]


def _random_walk(base: float, hours: int) -> list[float]:
    values, val = [], base
    for h in range(hours):
        diurnal = 1.0 + 0.3 * math.sin(math.pi * (h % 24 - 6) / 12)
        val = max(0.5, val + random.gauss(0, 0.12 * base)) * diurnal / 1.15
        if random.random() < 0.015:
            val *= random.uniform(2.5, 4.0)
        values.append(round(val, 2))
    return values


async def seed(db_url: str = "sqlite+aiosqlite:///./urbanpulse.db") -> None:
    connect_args = {"check_same_thread": False} if "sqlite" in db_url else {}
    engine = create_async_engine(db_url, connect_args=connect_args)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with factory() as s:
        # Countries
        country_map: dict[str, int] = {}
        for iso, name in COUNTRIES.items():
            row = (await s.execute(select(DimCountry).where(DimCountry.iso_code == iso))).scalars().first()
            if not row:
                row = DimCountry(iso_code=iso, name=name, continent="Europe")
                s.add(row); await s.flush()
            country_map[iso] = row.country_id

        # Parameters (use .first() to handle duplicates from real API seeding)
        param_map: dict[str, int] = {}
        for i, param in enumerate(PARAMS, 1):
            row = (await s.execute(select(DimParameter).where(DimParameter.name == param))).scalars().first()
            if not row:
                g = WHO_GUIDELINES.get(param, {})
                row = DimParameter(
                    openaq_id=1000 + i, name=param,
                    display_name=g.get("display", param.upper()),
                    unit=g.get("unit", "µg/m³"),
                    who_annual_guideline=g.get("annual"),
                    who_24h_guideline=g.get("daily"),
                )
                s.add(row); await s.flush()
            param_map[param] = row.parameter_id

        # Locations
        loc_map: dict[str, int] = {}
        for i, ci in enumerate(CITIES, 1):
            row = (await s.execute(select(DimLocation).where(DimLocation.openaq_id == 2000 + i))).scalar_one_or_none()
            if not row:
                row = DimLocation(
                    openaq_id=2000 + i, name=f"{ci['city']} Central Station",
                    city=ci["city"], country_id=country_map[ci["country"]],
                    latitude=ci["lat"], longitude=ci["lon"],
                    is_mobile=False, is_monitor=True,
                )
                s.add(row); await s.flush()
            loc_map[ci["city"]] = row.location_id

        await s.commit()

    # Measurements — bulk insert via core SQL to avoid BigInteger ORM issue
    hours = 7 * 24
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    total = 0

    async with engine.begin() as conn:
        for ci in CITIES:
            city = ci["city"]
            loc_id = loc_map[city]
            bases = BASE_CONCENTRATIONS[city]

            rows = []
            for param in PARAMS:
                pid = param_map[param]
                series = _random_walk(bases[param], hours)
                for h, val in enumerate(series):
                    ts = now - timedelta(hours=hours - h)
                    rows.append({
                        "location_id": loc_id,
                        "parameter_id": pid,
                        "measured_at": ts,
                        "value": val,
                        "unit": "ug/m3",
                    })

            is_pg = "postgresql" in db_url
            upsert_sql = (
                """
                    INSERT INTO fact_measurement
                        (location_id, parameter_id, measured_at, value, unit)
                    VALUES
                        (:location_id, :parameter_id, :measured_at, :value, :unit)
                    ON CONFLICT DO NOTHING
                """
                if is_pg else
                """
                    INSERT OR IGNORE INTO fact_measurement
                        (location_id, parameter_id, measured_at, value, unit)
                    VALUES
                        (:location_id, :parameter_id, :measured_at, :value, :unit)
                """
            )
            await conn.execute(text(upsert_sql), rows)
            total += len(rows)
            print(f"  OK {city}: {len(rows)} rows")

    print(f"\nDone: {total} measurements across {len(CITIES)} cities.")
    await engine.dispose()


if __name__ == "__main__":
    import os
    print("Seeding UrbanPulse demo data...")
    db_url = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./urbanpulse.db")
    asyncio.run(seed(db_url))
    print("Dashboard: http://localhost:8501")
