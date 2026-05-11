"""Worker entry point — starts the scheduler and blocks forever."""

import asyncio
import logging

from urbanpulse.config import settings
from urbanpulse.database import init_db
from urbanpulse.worker.scheduler import start_scheduler, stop_scheduler
from urbanpulse.worker.tasks import startup_task

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    logger.info("UrbanPulse worker starting up...")
    await init_db()
    await startup_task()
    scheduler = start_scheduler()
    try:
        while True:
            await asyncio.sleep(60)
    finally:
        stop_scheduler()
        logger.info("UrbanPulse worker shut down.")


if __name__ == "__main__":
    asyncio.run(main())
