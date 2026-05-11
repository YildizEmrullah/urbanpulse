"""FastAPI application factory with lifespan, middleware, and router registration."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from urbanpulse.api.routers import anomalies, health_index, locations, measurements, predictions
from urbanpulse.config import settings
from urbanpulse.database import init_db

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: initialise DB and start background scheduler. Shutdown: stop scheduler."""
    logger.info("UrbanPulse API starting up...")
    await init_db()
    from urbanpulse.worker.tasks import startup_task
    from urbanpulse.worker.scheduler import start_scheduler
    await startup_task()
    scheduler = start_scheduler()
    yield
    from urbanpulse.worker.scheduler import stop_scheduler
    stop_scheduler()
    logger.info("UrbanPulse API shut down.")


app = FastAPI(
    title="UrbanPulse API",
    description=(
        "Real-time European air quality intelligence platform. "
        "Data from ESA OpenAQ network — 20+ cities, 6 pollutants, "
        "XGBoost 24h forecasting, IsolationForest anomaly detection, EU CAQI health index."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

API_PREFIX = "/api/v1"
app.include_router(locations.router,    prefix=API_PREFIX)
app.include_router(measurements.router, prefix=API_PREFIX)
app.include_router(predictions.router,  prefix=API_PREFIX)
app.include_router(anomalies.router,    prefix=API_PREFIX)
app.include_router(health_index.router, prefix=API_PREFIX)


@app.get("/", tags=["System"])
async def root():
    return {
        "service": "UrbanPulse",
        "version": "1.0.0",
        "docs": "/docs",
        "description": "European air quality intelligence platform",
        "endpoints": {
            "locations":    f"{API_PREFIX}/locations",
            "measurements": f"{API_PREFIX}/measurements",
            "predictions":  f"{API_PREFIX}/predictions",
            "anomalies":    f"{API_PREFIX}/anomalies",
            "health_index": f"{API_PREFIX}/health-index/ranking",
        },
    }


@app.get("/health", tags=["System"])
async def health():
    return {"status": "ok", "database": settings.database_url.split("///")[0]}
