"""Predictions router: trigger ML forecasting and retrieve results."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from urbanpulse.api.dependencies import db
from urbanpulse.models.dimensions import DimLocation, DimParameter
from urbanpulse.models.facts import FactMlPrediction
from urbanpulse.worker.cache import cache_get, cache_set

router = APIRouter(prefix="/predictions", tags=["Predictions"])


@router.get("/{location_id}/{parameter}")
async def get_predictions(
    location_id: int,
    parameter: str,
    session: AsyncSession = Depends(db),
):
    """Return the latest 24-hour forecast for a (location, parameter) pair."""
    cache_key = f"pred:{location_id}:{parameter}"
    cached = await cache_get(cache_key)
    if cached:
        return cached

    now = datetime.now(timezone.utc)
    stmt = (
        select(FactMlPrediction)
        .where(
            FactMlPrediction.location_id == location_id,
            FactMlPrediction.predicted_for >= now,
        )
        .order_by(FactMlPrediction.predicted_for)
        .limit(24)
    )
    preds = (await session.execute(stmt)).scalars().all()

    data = [
        {
            "predicted_for": p.predicted_for.isoformat(),
            "predicted_value": float(p.predicted_value),
            "lower_bound": float(p.lower_bound) if p.lower_bound else None,
            "upper_bound": float(p.upper_bound) if p.upper_bound else None,
            "model_version": p.model_version,
            "mae": float(p.mae) if p.mae else None,
        }
        for p in preds
    ]
    response = {"location_id": location_id, "parameter": parameter, "horizon_hours": 24, "forecasts": data}
    await cache_set(cache_key, response, ttl=600)
    return response


@router.post("/trigger")
async def trigger_prediction(
    location_id: int,
    parameter: str,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(db),
):
    """Trigger on-demand model training and forecast generation."""
    loc = (await session.execute(select(DimLocation).where(DimLocation.location_id == location_id))).scalar_one_or_none()
    if loc is None:
        raise HTTPException(status_code=404, detail="Location not found")

    background_tasks.add_task(_run_prediction_job, location_id, parameter)
    return {"status": "queued", "location_id": location_id, "parameter": parameter}


async def _run_prediction_job(location_id: int, parameter: str) -> None:
    """Background task: train model and store predictions in DB."""
    import pandas as pd
    from urbanpulse.database import AsyncSessionLocal
    from urbanpulse.ml.forecaster import train as train_model, predict
    from urbanpulse.models.facts import FactMlPrediction

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("""
                SELECT m.measured_at, m.value
                FROM fact_measurement m
                JOIN dim_parameter p ON p.parameter_id = m.parameter_id
                WHERE m.location_id = :loc AND p.name = :param
                ORDER BY m.measured_at DESC LIMIT 2000
            """),
            {"loc": location_id, "param": parameter},
        )
        rows = result.fetchall()
        if not rows:
            return

        df = pd.DataFrame(rows, columns=["measured_at", "value"]).sort_values("measured_at")

        try:
            meta = train_model(df, location_id, parameter)
        except ValueError:
            meta = {"model_version": "xgb_v0", "mae": None, "rmse": None}

        forecasts = predict(df, location_id, parameter)
        if not forecasts:
            return

        param_result = await session.execute(
            select(DimParameter).where(DimParameter.name == parameter.lower())
        )
        param = param_result.scalar_one_or_none()
        if param is None:
            return

        for fc in forecasts:
            from datetime import datetime
            pred_for = datetime.fromisoformat(fc["predicted_for"])
            existing = (await session.execute(
                select(FactMlPrediction).where(
                    FactMlPrediction.location_id == location_id,
                    FactMlPrediction.parameter_id == param.parameter_id,
                    FactMlPrediction.model_version == meta["model_version"],
                    FactMlPrediction.predicted_for == pred_for,
                )
            )).scalar_one_or_none()
            if existing is None:
                session.add(FactMlPrediction(
                    location_id=location_id,
                    parameter_id=param.parameter_id,
                    model_version=meta["model_version"],
                    predicted_for=pred_for,
                    predicted_value=fc["predicted_value"],
                    lower_bound=fc["lower_bound"],
                    upper_bound=fc["upper_bound"],
                    mae=meta.get("mae"),
                    rmse=meta.get("rmse"),
                ))
        await session.commit()
