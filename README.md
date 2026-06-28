---
title: UrbanPulse
emoji: 🌍
colorFrom: blue
colorTo: green
sdk: streamlit
sdk_version: 1.35.0
app_file: app.py
pinned: false
---

# UrbanPulse 🌍

> **Real-time European Air Quality Intelligence** — data engineering, XGBoost forecasting, anomaly detection, EU CAQI health index, FastAPI + Streamlit, Docker Compose.

[![CI](https://github.com/yourusername/urbanpulse/actions/workflows/ci.yml/badge.svg)](https://github.com/yourusername/urbanpulse/actions)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111%2B-009688)](https://fastapi.tiangolo.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## Overview

UrbanPulse ingests live air quality measurements from **15 European cities** via the [OpenAQ v3 API](https://api.openaq.org), stores them in a star-schema data warehouse, trains XGBoost time-series models to generate **24-hour PM2.5/NO₂/O₃ forecasts**, runs IsolationForest **anomaly detection**, and exposes everything through a **FastAPI** backend and **Streamlit** dashboard.

### Key features

| Feature | Details |
|---------|---------|
| **Data sources** | OpenAQ v3 (20+ stations), Open-Meteo weather API |
| **Cities** | Berlin, Munich, Hamburg, Paris, London, Amsterdam, Vienna, Warsaw, Prague + 6 more |
| **Pollutants** | PM2.5, PM10, NO₂, O₃, SO₂, CO |
| **Forecasting** | XGBoost + sklearn Pipeline, 30-feature engineering, 24h horizon |
| **Anomaly detection** | IsolationForest (200 estimators) + z-score fallback |
| **Health index** | Official EU Common Air Quality Index (CAQI) with 5 bands |
| **Scheduling** | APScheduler: ingest every 60 min, retrain every 24 h, anomaly scan every 30 min |
| **Caching** | Redis with transparent in-memory dict fallback |
| **Database** | SQLite (dev) / PostgreSQL (prod) — async SQLAlchemy 2.0 |
| **Migrations** | Alembic versioned migrations |
| **API** | FastAPI with OpenAPI docs at `/docs` |
| **Dashboard** | 5-page Streamlit app (map, time series, forecast, anomalies, ranking) |
| **Containers** | Docker Compose: postgres + redis + api + worker + dashboard |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         UrbanPulse                              │
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐  │
│  │  OpenAQ v3   │    │  Open-Meteo  │    │  APScheduler     │  │
│  │  (live data) │    │  (weather)   │    │  (background)    │  │
│  └──────┬───────┘    └──────┬───────┘    └────────┬─────────┘  │
│         │                  │                      │             │
│         ▼                  ▼                      ▼             │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │               Ingestion Pipeline (httpx async)           │  │
│  │  seed_parameters → seed_locations → ingest_measurements  │  │
│  └──────────────────────────┬───────────────────────────────┘  │
│                             │                                   │
│                             ▼                                   │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │          Star Schema Data Warehouse (SQLAlchemy)         │  │
│  │  dim_country  dim_location  dim_parameter                │  │
│  │  fact_measurement  fact_ml_prediction  fact_anomaly      │  │
│  └──────────────────────────┬───────────────────────────────┘  │
│                             │                                   │
│              ┌──────────────┼──────────────┐                   │
│              ▼              ▼              ▼                    │
│  ┌─────────────────┐ ┌──────────┐ ┌──────────────────┐        │
│  │ XGBoost 24h     │ │ ISO-     │ │ EU CAQI          │        │
│  │ Forecaster      │ │ Forest   │ │ Health Index     │        │
│  │ (30 features)   │ │ Anomaly  │ │ (5 bands)        │        │
│  └────────┬────────┘ └────┬─────┘ └────────┬─────────┘        │
│           │               │                │                    │
│           └───────────────┴────────────────┘                   │
│                           │                                     │
│                           ▼                                     │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                   FastAPI  /api/v1                       │  │
│  │  /locations  /measurements  /predictions  /anomalies     │  │
│  │  /health-index/ranking          Redis cache (TTL 5min)   │  │
│  └──────────────────────────┬───────────────────────────────┘  │
│                             │                                   │
│                             ▼                                   │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │            Streamlit Dashboard (5 pages)                 │  │
│  │  🗺️ City Map  📈 Time Series  🔮 Forecast               │  │
│  │  ⚠️ Anomalies  🏆 Health Ranking                        │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Quick Start

### Option A — Local (SQLite, no Docker)

```bash
# 1. Clone and install
git clone https://github.com/yourusername/urbanpulse.git
cd urbanpulse
pip install -e ".[dev]"

# 2. (Optional) set OpenAQ API key for higher rate limits
cp .env.example .env
# Edit .env: OPENAQ_API_KEY=your_key_here

# 3. Start the API (seeds DB on first boot, runs background ingestion)
uvicorn urbanpulse.api.main:app --reload

# 4. In a second terminal, start the dashboard
streamlit run src/urbanpulse/dashboard/app.py
```

- API docs: http://localhost:8000/docs
- Dashboard: http://localhost:8501
- Health check: http://localhost:8000/health

### Option B — Docker Compose (PostgreSQL + Redis)

```bash
git clone https://github.com/yourusername/urbanpulse.git
cd urbanpulse
cp .env.example .env        # set OPENAQ_API_KEY and POSTGRES_PASSWORD
docker compose up --build
```

| Service | URL |
|---------|-----|
| API | http://localhost:8000 |
| API docs | http://localhost:8000/docs |
| Dashboard | http://localhost:8501 |

---

## Project Structure

```
urbanpulse/
├── src/urbanpulse/
│   ├── config.py               # Pydantic Settings — all env vars
│   ├── database.py             # Async SQLAlchemy engine + Base
│   ├── models/
│   │   ├── dimensions.py       # DimCountry, DimLocation, DimParameter
│   │   └── facts.py            # FactMeasurement, FactMlPrediction, FactAnomalyEvent
│   ├── ingestion/
│   │   ├── openaq_client.py    # Async httpx client — 15 European cities
│   │   └── pipeline.py         # ETL: seed + upsert measurements
│   ├── ml/
│   │   ├── features.py         # 30-feature time-series engineering
│   │   ├── forecaster.py       # XGBoost 24h prediction pipeline
│   │   ├── anomaly.py          # IsolationForest + z-score fallback
│   │   └── health_index.py     # EU CAQI computation
│   ├── api/
│   │   ├── main.py             # FastAPI app + lifespan
│   │   └── routers/            # locations, measurements, predictions, anomalies, health_index
│   ├── worker/
│   │   ├── tasks.py            # Async background tasks
│   │   ├── scheduler.py        # APScheduler setup
│   │   └── cache.py            # Redis + in-memory fallback
│   └── dashboard/
│       ├── app.py              # Streamlit 5-page app
│       └── api_client.py       # httpx wrapper for FastAPI
├── alembic/                    # Database migrations
│   └── versions/
│       └── 0001_initial_schema.py
├── tests/
│   ├── unit/                   # test_health_index, test_features, test_anomaly
│   └── integration/            # test_api — full FastAPI + in-memory SQLite
├── docker-compose.yml          # postgres + redis + api + dashboard
├── Dockerfile                  # Multi-stage: base → source → api/worker/dashboard
└── pyproject.toml
```

---

## Data Model — Star Schema

```
dim_country ──┐
              ├── dim_location ──┬── fact_measurement
dim_parameter ─┘                ├── fact_ml_prediction
                                └── fact_anomaly_event
```

**Dimension tables** store slowly-changing metadata (countries, stations, pollutant definitions + WHO guidelines). **Fact tables** store time-stamped events with foreign keys into dimensions — classical Kimball star schema for analytical queries.

---

## ML Pipeline

### 24-Hour Forecasting (XGBoost)

Feature set (30 features):

- **Temporal:** hour, day-of-week, month, is-weekend, is-rush-hour
- **Cyclical encodings:** sin/cos of hour and day-of-week (prevents discontinuities)
- **Lags:** 1h, 2h, 3h, 6h, 12h, 24h, 48h
- **Rolling statistics:** mean, std, max over 3h/6h/12h/24h windows
- **Trend:** Δ1h, Δ24h

Model: `XGBRegressor` wrapped in `sklearn.Pipeline` with `StandardScaler`. Trained separately per (location, pollutant) pair. Confidence interval: ±15% of predicted value.

### Anomaly Detection (IsolationForest)

- 200 estimators, 5% contamination rate
- Severity mapping by anomaly score + WHO guideline exceedance:
  - `critical`: score < −0.4 or value > 2× WHO daily limit
  - `high`: score < −0.3 or value > 1.5× WHO daily limit
  - `medium`: score < −0.2 or any exceedance
  - `low`: flagged by model but below WHO limits

### EU Common Air Quality Index (CAQI)

Official EU standard: maximum sub-index across PM2.5, PM10, NO₂, O₃.

| Band | CAQI | Color |
|------|------|-------|
| Very Low | 0–25 | 🟢 `#79BC6A` |
| Low | 25–50 | 🟡 `#BBCF4C` |
| Medium | 50–75 | 🟠 `#EEC20B` |
| High | 75–100 | 🔴 `#F29305` |
| Very High | 100+ | ⛔ `#E8416F` |

---

## API Reference

All endpoints prefixed with `/api/v1`. Interactive docs at `/docs`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/locations` | List monitoring stations (filter by city/country) |
| GET | `/locations/{id}` | Station detail + latest measurements |
| GET | `/measurements` | Hourly/daily aggregated time series |
| GET | `/predictions/{loc}/{param}` | 24h forecast values |
| POST | `/predictions/trigger` | Queue immediate forecast job |
| GET | `/anomalies` | Anomaly events (filter by severity, date range) |
| GET | `/anomalies/summary` | Severity counts summary |
| GET | `/health-index/ranking` | All cities ranked by current CAQI |
| GET | `/health-index?city=Berlin` | Single-city CAQI detail |
| GET | `/health` | Service health check |

---

## Configuration

All settings via environment variables (or `.env` file):

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite+aiosqlite:///./urbanpulse.db` | SQLAlchemy async URL |
| `REDIS_URL` | `None` | Optional Redis (in-memory fallback if unset) |
| `OPENAQ_API_KEY` | `None` | Optional — increases rate limits |
| `ADMIN_TOKEN` | `changeme-in-production` | Bearer token for admin endpoints |
| `LOG_LEVEL` | `INFO` | Python logging level |
| `CACHE_TTL_SECONDS` | `300` | Cache TTL (5 minutes) |
| `INGEST_INTERVAL_MINUTES` | `60` | How often to pull new measurements |
| `RETRAIN_INTERVAL_HOURS` | `24` | How often to retrain ML models |

---

## Testing

```bash
# Unit tests (no network, no DB)
pytest tests/unit/ -v

# Integration tests (in-memory SQLite)
pytest tests/integration/ -v

# All tests
pytest tests/ -v

# Lint
ruff check src/ tests/
```

---

## License

MIT — see [LICENSE](LICENSE).

---

*Built as a portfolio project demonstrating production-grade data engineering + MLOps patterns. Data from [OpenAQ](https://openaq.org) (CC BY 4.0).*
