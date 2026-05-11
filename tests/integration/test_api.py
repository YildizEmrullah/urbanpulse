"""Integration tests for FastAPI endpoints using in-memory SQLite."""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from urbanpulse.database import Base
import urbanpulse.models  # noqa: F401 — registers ORM classes
from urbanpulse.models.dimensions import DimCountry, DimLocation, DimParameter
from urbanpulse.api.main import app
from urbanpulse.api.dependencies import db as db_dependency

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="function")
async def test_engine():
    engine = create_async_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def seeded_client(test_engine):
    session_factory = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)

    async def override_db():
        async with session_factory() as session:
            yield session

    async with session_factory() as session:
        country = DimCountry(iso_code="DE", name="Germany", continent="Europe")
        session.add(country)
        await session.flush()
        loc = DimLocation(
            openaq_id=999, name="Test Station", city="Berlin",
            country_id=country.country_id, latitude=52.52, longitude=13.40,
            is_mobile=False, is_monitor=True,
        )
        session.add(loc)
        param = DimParameter(
            openaq_id=1, name="pm25", display_name="PM2.5",
            unit="µg/m³", who_annual_guideline=5.0, who_24h_guideline=15.0,
        )
        session.add(param)
        await session.commit()

    app.dependency_overrides[db_dependency] = override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_root_endpoint(seeded_client):
    r = await seeded_client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "UrbanPulse"


@pytest.mark.asyncio
async def test_health_endpoint(seeded_client):
    r = await seeded_client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_list_locations_empty(seeded_client):
    r = await seeded_client.get("/api/v1/locations")
    assert r.status_code == 200
    body = r.json()
    assert "results" in body
    assert isinstance(body["results"], list)


@pytest.mark.asyncio
async def test_list_locations_with_data(seeded_client):
    r = await seeded_client.get("/api/v1/locations?city=Berlin")
    assert r.status_code == 200
    body = r.json()
    assert len(body["results"]) >= 1
    assert body["results"][0]["city"] == "Berlin"


@pytest.mark.asyncio
async def test_location_not_found(seeded_client):
    r = await seeded_client.get("/api/v1/locations/99999")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_health_ranking_empty(seeded_client):
    r = await seeded_client.get("/api/v1/health-index/ranking")
    assert r.status_code == 200
    body = r.json()
    assert "ranking" in body


@pytest.mark.asyncio
async def test_anomaly_summary(seeded_client):
    r = await seeded_client.get("/api/v1/anomalies/summary")
    assert r.status_code == 200
    body = r.json()
    assert "summary" in body


@pytest.mark.asyncio
async def test_measurements_endpoint(seeded_client):
    r = await seeded_client.get("/api/v1/measurements?location_id=1&parameter=pm25")
    assert r.status_code in (200, 422)
