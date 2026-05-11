"""Dimension tables: DimCountry, DimLocation, DimParameter."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from urbanpulse.database import Base


class DimCountry(Base):
    __tablename__ = "dim_country"

    country_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    iso_code: Mapped[str] = mapped_column(String(2), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    continent: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    locations: Mapped[list["DimLocation"]] = relationship(back_populates="country")

    def __repr__(self) -> str:
        return f"<DimCountry {self.iso_code}: {self.name}>"


class DimLocation(Base):
    __tablename__ = "dim_location"

    location_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    openaq_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    city: Mapped[str | None] = mapped_column(String(100), index=True)
    country_id: Mapped[int | None] = mapped_column(ForeignKey("dim_country.country_id"), index=True)
    latitude: Mapped[float | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[float | None] = mapped_column(Numeric(9, 6))
    altitude_m: Mapped[float | None] = mapped_column(Numeric(7, 2))
    is_mobile: Mapped[bool] = mapped_column(Boolean, default=False)
    is_monitor: Mapped[bool] = mapped_column(Boolean, default=True)
    owner_name: Mapped[str | None] = mapped_column(String(255))
    provider_name: Mapped[str | None] = mapped_column(String(255))
    first_updated: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_updated: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    country: Mapped["DimCountry | None"] = relationship(back_populates="locations")
    measurements: Mapped[list["FactMeasurement"]] = relationship(back_populates="location")

    def __repr__(self) -> str:
        return f"<DimLocation #{self.openaq_id}: {self.name}, {self.city}>"


class DimParameter(Base):
    __tablename__ = "dim_parameter"

    parameter_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    openaq_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    # WHO Air Quality Guidelines 2021
    who_annual_guideline: Mapped[float | None] = mapped_column(Numeric(8, 3))
    who_24h_guideline: Mapped[float | None] = mapped_column(Numeric(8, 3))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    measurements: Mapped[list["FactMeasurement"]] = relationship(back_populates="parameter")

    def __repr__(self) -> str:
        return f"<DimParameter {self.name} [{self.unit}]>"


# WHO 2021 Air Quality Guidelines seed data
WHO_GUIDELINES: dict[str, dict] = {
    "pm25":  {"annual": 5.0,   "daily": 15.0,  "unit": "µg/m³", "display": "PM2.5"},
    "pm10":  {"annual": 15.0,  "daily": 45.0,  "unit": "µg/m³", "display": "PM10"},
    "no2":   {"annual": 10.0,  "daily": 25.0,  "unit": "µg/m³", "display": "NO₂"},
    "o3":    {"annual": None,  "daily": 100.0, "unit": "µg/m³", "display": "O₃"},
    "so2":   {"annual": None,  "daily": 40.0,  "unit": "µg/m³", "display": "SO₂"},
    "co":    {"annual": None,  "daily": 4000.0,"unit": "µg/m³", "display": "CO"},
}
