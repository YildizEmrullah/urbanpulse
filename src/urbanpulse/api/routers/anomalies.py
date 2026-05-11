"""Anomalies router: list and summarize pollution anomaly events."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from urbanpulse.api.dependencies import db, paginate
from urbanpulse.models.dimensions import DimLocation, DimParameter
from urbanpulse.models.facts import FactAnomalyEvent

router = APIRouter(prefix="/anomalies", tags=["Anomalies"])


@router.get("")
async def list_anomalies(
    severity: str | None = Query(default=None, pattern="^(low|medium|high|critical)$"),
    resolved: bool | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    pagination: dict = Depends(paginate),
    session: AsyncSession = Depends(db),
):
    """List anomaly events with optional filters."""
    if date_to is None:
        date_to = datetime.now(timezone.utc)
    if date_from is None:
        date_from = date_to - timedelta(days=30)

    stmt = select(FactAnomalyEvent).where(
        FactAnomalyEvent.detected_at >= date_from,
        FactAnomalyEvent.detected_at <= date_to,
    )
    if severity:
        stmt = stmt.where(FactAnomalyEvent.severity == severity)
    if resolved is not None:
        stmt = stmt.where(FactAnomalyEvent.resolved == resolved)
    stmt = stmt.order_by(FactAnomalyEvent.detected_at.desc()).offset(pagination["offset"]).limit(pagination["limit"])

    events = (await session.execute(stmt)).scalars().all()
    return {
        "count": len(events),
        "results": [
            {
                "event_id": e.event_id,
                "location_id": e.location_id,
                "parameter_id": e.parameter_id,
                "detected_at": e.detected_at.isoformat(),
                "peak_value": float(e.peak_value) if e.peak_value else None,
                "anomaly_score": float(e.anomaly_score) if e.anomaly_score else None,
                "severity": e.severity,
                "who_exceedance": e.who_exceedance,
                "resolved": e.resolved,
            }
            for e in events
        ],
    }


@router.get("/summary")
async def anomaly_summary(session: AsyncSession = Depends(db)):
    """Count anomaly events per severity for the last 30 days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    stmt = (
        select(FactAnomalyEvent.severity, func.count().label("count"))
        .where(FactAnomalyEvent.detected_at >= cutoff)
        .group_by(FactAnomalyEvent.severity)
    )
    rows = (await session.execute(stmt)).all()
    return {
        "period_days": 30,
        "summary": {row[0]: row[1] for row in rows},
    }
