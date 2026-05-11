"""Initial star-schema tables.

Revision ID: 0001
Revises:
Create Date: 2025-01-01 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Dimension: country ───────────────────────────────────────────────────
    op.create_table(
        "dim_country",
        sa.Column("country_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("iso_code", sa.String(length=3), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("continent", sa.String(length=60), nullable=True),
        sa.PrimaryKeyConstraint("country_id"),
        sa.UniqueConstraint("iso_code"),
    )

    # ── Dimension: location ──────────────────────────────────────────────────
    op.create_table(
        "dim_location",
        sa.Column("location_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("openaq_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("city", sa.String(length=120), nullable=True),
        sa.Column("country_id", sa.Integer(), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("is_mobile", sa.Boolean(), nullable=True),
        sa.Column("is_monitor", sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(["country_id"], ["dim_country.country_id"]),
        sa.PrimaryKeyConstraint("location_id"),
        sa.UniqueConstraint("openaq_id"),
    )

    # ── Dimension: parameter ─────────────────────────────────────────────────
    op.create_table(
        "dim_parameter",
        sa.Column("parameter_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("openaq_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=True),
        sa.Column("unit", sa.String(length=30), nullable=True),
        sa.Column("who_annual_guideline", sa.Float(), nullable=True),
        sa.Column("who_24h_guideline", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("parameter_id"),
        sa.UniqueConstraint("openaq_id"),
    )

    # ── Fact: measurement ────────────────────────────────────────────────────
    op.create_table(
        "fact_measurement",
        sa.Column("measurement_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("location_id", sa.Integer(), nullable=False),
        sa.Column("parameter_id", sa.Integer(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("unit", sa.String(length=30), nullable=True),
        sa.ForeignKeyConstraint(["location_id"], ["dim_location.location_id"]),
        sa.ForeignKeyConstraint(["parameter_id"], ["dim_parameter.parameter_id"]),
        sa.PrimaryKeyConstraint("measurement_id"),
        sa.UniqueConstraint("location_id", "parameter_id", "measured_at", name="uq_measurement"),
    )
    op.create_index("ix_fact_measurement_measured_at", "fact_measurement", ["measured_at"])
    op.create_index("ix_fact_measurement_location_param", "fact_measurement", ["location_id", "parameter_id"])

    # ── Fact: ML prediction ──────────────────────────────────────────────────
    op.create_table(
        "fact_ml_prediction",
        sa.Column("prediction_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("location_id", sa.Integer(), nullable=False),
        sa.Column("parameter_id", sa.Integer(), nullable=False),
        sa.Column("model_version", sa.String(length=64), nullable=False),
        sa.Column("predicted_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("predicted_value", sa.Float(), nullable=False),
        sa.Column("lower_bound", sa.Float(), nullable=True),
        sa.Column("upper_bound", sa.Float(), nullable=True),
        sa.Column("mae", sa.Float(), nullable=True),
        sa.Column("rmse", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["location_id"], ["dim_location.location_id"]),
        sa.ForeignKeyConstraint(["parameter_id"], ["dim_parameter.parameter_id"]),
        sa.PrimaryKeyConstraint("prediction_id"),
        sa.UniqueConstraint("location_id", "parameter_id", "model_version", "predicted_for", name="uq_prediction"),
    )
    op.create_index("ix_fact_ml_prediction_predicted_for", "fact_ml_prediction", ["predicted_for"])

    # ── Fact: anomaly event ──────────────────────────────────────────────────
    op.create_table(
        "fact_anomaly_event",
        sa.Column("anomaly_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("location_id", sa.Integer(), nullable=False),
        sa.Column("parameter_id", sa.Integer(), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("anomaly_score", sa.Float(), nullable=True),
        sa.Column("peak_value", sa.Float(), nullable=True),
        sa.Column("who_exceedance", sa.Boolean(), nullable=True),
        sa.CheckConstraint("severity IN ('low','medium','high','critical')", name="ck_severity"),
        sa.ForeignKeyConstraint(["location_id"], ["dim_location.location_id"]),
        sa.ForeignKeyConstraint(["parameter_id"], ["dim_parameter.parameter_id"]),
        sa.PrimaryKeyConstraint("anomaly_id"),
    )
    op.create_index("ix_fact_anomaly_event_detected_at", "fact_anomaly_event", ["detected_at"])


def downgrade() -> None:
    op.drop_table("fact_anomaly_event")
    op.drop_table("fact_ml_prediction")
    op.drop_table("fact_measurement")
    op.drop_table("dim_parameter")
    op.drop_table("dim_location")
    op.drop_table("dim_country")
