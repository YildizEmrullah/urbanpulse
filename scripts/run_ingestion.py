"""Run a single ingestion cycle standalone (no API server needed)."""
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)

from urbanpulse.database import init_db, AsyncSessionLocal
from urbanpulse.ingestion.pipeline import seed_parameters, seed_locations, ingest_recent_measurements


async def main():
    print("Initialising database...")
    await init_db()

    async with AsyncSessionLocal() as session:
        print("Seeding parameters...")
        param_map = await seed_parameters(session)
        print(f"  {len(param_map)} parameters ready: {list(param_map.keys())}")

        print("Seeding locations (may take 1-2 min)...")
        loc_map = await seed_locations(session)
        print(f"  {len(loc_map)} stations found")

        print("Ingesting measurements (may take 5-15 min)...")
        count = await ingest_recent_measurements(session, loc_map, param_map, hours_back=72)
        print(f"\nDone: {count} measurements inserted")


if __name__ == "__main__":
    asyncio.run(main())
