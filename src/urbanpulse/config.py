"""Centralized configuration — all settings from environment variables."""

from pathlib import Path
from typing import Optional

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).parents[2]  # src/urbanpulse/config.py → project root


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Database ──────────────────────────────────────────────────────
    database_url: str = Field(
        default=f"sqlite+aiosqlite:///{PROJECT_ROOT}/urbanpulse.db",
        description="SQLAlchemy async URL. SQLite by default; set postgresql+asyncpg://... for Postgres.",
    )

    # ── Redis (optional) ─────────────────────────────────────────────
    redis_url: Optional[str] = Field(default=None)

    # ── External APIs ────────────────────────────────────────────────
    openaq_api_key: Optional[str] = Field(default=None)
    openaq_base_url: str = Field(default="https://api.openaq.org/v3")
    open_meteo_base_url: str = Field(default="https://api.open-meteo.com/v1")

    # ── Security ──────────────────────────────────────────────────────
    admin_token: str = Field(default="changeme-in-production")

    # ── App behaviour ─────────────────────────────────────────────────
    log_level: str = Field(default="INFO")
    cache_ttl_seconds: int = Field(default=300)
    ingest_interval_minutes: int = Field(default=60)
    retrain_interval_hours: int = Field(default=24)

    # ── Paths ─────────────────────────────────────────────────────────
    models_dir: Path = Field(default=PROJECT_ROOT / "models")

    @model_validator(mode="after")
    def _ensure_dirs(self) -> "Settings":
        self.models_dir.mkdir(parents=True, exist_ok=True)
        return self

    @property
    def is_sqlite(self) -> bool:
        return "sqlite" in self.database_url

    @property
    def is_postgres(self) -> bool:
        return "postgresql" in self.database_url


settings = Settings()
