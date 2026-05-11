"""APScheduler background job runner — used both inside FastAPI lifespan and standalone."""

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from urbanpulse.config import settings

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="UTC")
    return _scheduler


def start_scheduler() -> AsyncIOScheduler:
    """Configure and start the background job scheduler."""
    from urbanpulse.worker.tasks import anomaly_scan_task, ingest_task, retrain_task

    scheduler = get_scheduler()

    scheduler.add_job(
        ingest_task,
        trigger="interval",
        minutes=settings.ingest_interval_minutes,
        id="ingest",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        retrain_task,
        trigger="interval",
        hours=settings.retrain_interval_hours,
        id="retrain",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        anomaly_scan_task,
        trigger="interval",
        minutes=30,
        id="anomaly_scan",
        replace_existing=True,
        max_instances=1,
    )

    if not scheduler.running:
        scheduler.start()
        logger.info(
            "Scheduler started — ingest every %dm, retrain every %dh, anomaly scan every 30m",
            settings.ingest_interval_minutes,
            settings.retrain_interval_hours,
        )
    return scheduler


def stop_scheduler() -> None:
    scheduler = get_scheduler()
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")


if __name__ == "__main__":
    """Run as a standalone worker process (used in Docker worker service)."""
    import logging
    logging.basicConfig(level=settings.log_level, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")

    async def main():
        from urbanpulse.database import init_db
        from urbanpulse.worker.tasks import startup_task

        await init_db()
        await startup_task()
        start_scheduler()
        logger.info("Worker running. Press Ctrl+C to stop.")
        try:
            while True:
                await asyncio.sleep(60)
        except (KeyboardInterrupt, SystemExit):
            stop_scheduler()

    asyncio.run(main())
