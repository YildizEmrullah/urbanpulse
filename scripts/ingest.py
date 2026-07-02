"""Standalone ingestion script for GitHub Actions cron job."""

import asyncio
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def main() -> None:
    from urbanpulse.database import AsyncSessionLocal, engine, init_db
    from urbanpulse.ingestion.pipeline import (
        ingest_recent_measurements,
        seed_locations,
        seed_parameters,
    )

    await init_db()

    async with AsyncSessionLocal() as session:
        param_map = await seed_parameters(session)
        loc_map = await seed_locations(session)
        count = await ingest_recent_measurements(session, loc_map, param_map, hours_back=2)
        logger.info("Ingested %d new measurements", count)

    await engine.dispose()


if __name__ == "__main__":
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        logger.error("DATABASE_URL not set — aborting")
        sys.exit(1)
    asyncio.run(main())
