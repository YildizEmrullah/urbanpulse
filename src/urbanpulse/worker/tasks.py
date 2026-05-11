"""Scheduled background tasks: ingestion, ML retraining, anomaly detection."""

import logging

from sqlalchemy import select, text

from urbanpulse.database import AsyncSessionLocal
from urbanpulse.models.dimensions import DimLocation, DimParameter
from urbanpulse.models.facts import FactAnomalyEvent

logger = logging.getLogger(__name__)

# Module-level caches populated on first run
_openaq_to_db: dict[int, int] = {}
_param_name_to_id: dict[str, int] = {}


async def startup_task() -> None:
    """Run once on startup: seed DB, discover stations, ingest recent data.

    Skips live OpenAQ ingestion if demo data already exists.
    """
    logger.info("Running startup task...")
    async with AsyncSessionLocal() as session:
        from sqlalchemy import text as _text
        result = await session.execute(_text("SELECT COUNT(*) FROM fact_measurement"))
        existing_count = result.scalar()
        if existing_count > 0:
            logger.info("Demo/existing data detected (%d rows) — skipping live ingestion", existing_count)
            # Populate caches from existing DB data for scheduled tasks
            await _refresh_location_cache(session)
            await _refresh_param_cache(session)
            return

        from urbanpulse.ingestion.pipeline import (
            ingest_recent_measurements,
            seed_locations,
            seed_parameters,
        )
        global _openaq_to_db, _param_name_to_id
        _param_name_to_id = await seed_parameters(session)
        _openaq_to_db = await seed_locations(session)
        count = await ingest_recent_measurements(session, _openaq_to_db, _param_name_to_id, hours_back=72)
        logger.info("Startup ingestion: %d measurements", count)


async def ingest_task() -> None:
    """Fetch the latest hour of measurements for all known stations."""
    logger.info("Running scheduled ingestion...")
    async with AsyncSessionLocal() as session:
        from urbanpulse.ingestion.pipeline import ingest_recent_measurements, seed_locations
        if not _openaq_to_db:
            await _refresh_location_cache(session)
        count = await ingest_recent_measurements(session, _openaq_to_db, _param_name_to_id, hours_back=2)
        logger.info("Ingestion task: %d new measurements", count)


async def retrain_task() -> None:
    """Retrain XGBoost and IsolationForest models for all (location, parameter) pairs."""
    logger.info("Running scheduled ML retraining...")
    import pandas as pd
    from sqlalchemy import select

    async with AsyncSessionLocal() as session:
        # Load all measurements into a DataFrame
        result = await session.execute(
            text("""
                SELECT m.location_id, p.name AS parameter, m.measured_at, m.value
                FROM fact_measurement m
                JOIN dim_parameter p ON p.parameter_id = m.parameter_id
                ORDER BY m.location_id, p.name, m.measured_at
            """)
        )
        rows = result.fetchall()

    if not rows:
        logger.warning("No measurements available for training")
        return

    df = pd.DataFrame(rows, columns=["location_id", "parameter", "measured_at", "value"])

    from urbanpulse.ml.forecaster import train as train_forecast
    from urbanpulse.ml.anomaly import train_anomaly_detector

    for (loc_id, param), group in df.groupby(["location_id", "parameter"]):
        group = group[["measured_at", "value"]].copy()
        try:
            train_forecast(group, loc_id, param)
        except ValueError as exc:
            logger.debug("Forecast training skipped loc=%d param=%s: %s", loc_id, param, exc)
        try:
            train_anomaly_detector(group, loc_id, param)
        except Exception as exc:
            logger.debug("Anomaly training skipped loc=%d param=%s: %s", loc_id, param, exc)

    logger.info("Retraining complete")


async def anomaly_scan_task() -> None:
    """Detect anomalies in the last 24 hours and persist events."""
    logger.info("Running anomaly scan...")
    import pandas as pd

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("""
                SELECT m.location_id, p.parameter_id, p.name AS parameter,
                       p.who_24h_guideline, m.measured_at, m.value
                FROM fact_measurement m
                JOIN dim_parameter p ON p.parameter_id = m.parameter_id
                WHERE m.measured_at >= datetime('now', '-48 hours')
                ORDER BY m.location_id, p.name, m.measured_at
            """)
        )
        rows = result.fetchall()

    if not rows:
        return

    df = pd.DataFrame(rows, columns=["location_id", "parameter_id", "parameter", "who_24h_guideline", "measured_at", "value"])

    from urbanpulse.ml.anomaly import detect_anomalies

    total_events = 0
    async with AsyncSessionLocal() as session:
        for (loc_id, param), group in df.groupby(["location_id", "parameter"]):
            param_id = group["parameter_id"].iloc[0]
            who_guideline = group["who_24h_guideline"].iloc[0]
            hist = group[["measured_at", "value"]].copy()
            events = detect_anomalies(hist, loc_id, param, who_24h_guideline=who_guideline)
            for ev in events:
                session.add(FactAnomalyEvent(
                    location_id=loc_id,
                    parameter_id=param_id,
                    detected_at=ev["detected_at"],
                    peak_value=ev["peak_value"],
                    anomaly_score=ev["anomaly_score"],
                    severity=ev["severity"],
                    who_exceedance=ev["who_exceedance"],
                ))
                total_events += 1
        await session.commit()

    logger.info("Anomaly scan: %d new events stored", total_events)


async def _refresh_location_cache(session) -> None:
    """Refresh in-memory location cache from DB."""
    from sqlalchemy import select
    result = await session.execute(select(DimLocation))
    locs = result.scalars().all()
    for loc in locs:
        _openaq_to_db[loc.openaq_id] = loc.location_id


async def _refresh_param_cache(session) -> None:
    """Refresh in-memory parameter name→id cache from DB."""
    from sqlalchemy import select
    result = await session.execute(select(DimParameter))
    params = result.scalars().all()
    for p in params:
        _param_name_to_id[p.name] = p.parameter_id
