"""Fact tables: FactMeasurement, FactMlPrediction, FactAnomalyEvent."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from urbanpulse.database import Base


class FactMeasurement(Base):
    __tablename__ = "fact_measurement"
    __table_args__ = (
        UniqueConstraint("location_id", "parameter_id", "measured_at", name="uq_measurement"),
    )

    # Integer (not BigInteger) maps to INTEGER PRIMARY KEY in SQLite = rowid alias → auto-increments
    measurement_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("dim_location.location_id"), nullable=False, index=True)
    parameter_id: Mapped[int] = mapped_column(ForeignKey("dim_parameter.parameter_id"), nullable=False, index=True)
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    value: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(20))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    location: Mapped["DimLocation"] = relationship(back_populates="measurements")
    parameter: Mapped["DimParameter"] = relationship(back_populates="measurements")

    def __repr__(self) -> str:
        return f"<FactMeasurement loc={self.location_id} param={self.parameter_id} val={self.value} @ {self.measured_at}>"


class FactMlPrediction(Base):
    __tablename__ = "fact_ml_prediction"
    __table_args__ = (
        UniqueConstraint("location_id", "parameter_id", "model_version", "predicted_for", name="uq_prediction"),
    )

    prediction_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("dim_location.location_id"), nullable=False, index=True)
    parameter_id: Mapped[int] = mapped_column(ForeignKey("dim_parameter.parameter_id"), nullable=False, index=True)
    model_version: Mapped[str] = mapped_column(String(50), nullable=False)
    predicted_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    predicted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    predicted_value: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    lower_bound: Mapped[float | None] = mapped_column(Numeric(12, 4))
    upper_bound: Mapped[float | None] = mapped_column(Numeric(12, 4))
    mae: Mapped[float | None] = mapped_column(Numeric(10, 4))
    rmse: Mapped[float | None] = mapped_column(Numeric(10, 4))


class FactAnomalyEvent(Base):
    __tablename__ = "fact_anomaly_event"

    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("dim_location.location_id"), nullable=False, index=True)
    parameter_id: Mapped[int] = mapped_column(ForeignKey("dim_parameter.parameter_id"), nullable=False, index=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    peak_value: Mapped[float | None] = mapped_column(Numeric(12, 4))
    anomaly_score: Mapped[float | None] = mapped_column(Numeric(8, 6))
    severity: Mapped[str | None] = mapped_column(String(20))  # low, medium, high, critical
    who_exceedance: Mapped[bool] = mapped_column(Boolean, default=False)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
