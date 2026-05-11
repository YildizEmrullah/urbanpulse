"""Anomaly detection: IsolationForest + z-score ensemble."""

import logging
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from urbanpulse.config import settings
from urbanpulse.ml.features import build_features

logger = logging.getLogger(__name__)

MIN_ROWS = 48  # at least 2 days for anomaly baseline


def _model_path(location_id: int, parameter: str) -> Path:
    return settings.models_dir / f"isoforest_{location_id}_{parameter}.joblib"


def train_anomaly_detector(
    df: pd.DataFrame,
    location_id: int,
    parameter: str,
    contamination: float = 0.05,
) -> None:
    """Train IsolationForest on historical measurements."""
    df_feat = build_features(df, target_col="value").dropna(subset=["value", "lag_1h", "roll_mean_6h"])

    if len(df_feat) < MIN_ROWS:
        logger.warning("Not enough data to train anomaly detector for loc=%d param=%s", location_id, parameter)
        return

    feature_cols = ["value", "lag_1h", "roll_mean_6h", "roll_std_6h", "delta_1h", "hour"]
    X = df_feat[feature_cols].dropna().values
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    detector = IsolationForest(n_estimators=200, contamination=contamination, random_state=42, n_jobs=-1)
    detector.fit(X_scaled)

    joblib.dump({"detector": detector, "scaler": scaler, "feature_cols": feature_cols}, _model_path(location_id, parameter))
    logger.info("Anomaly detector trained for loc=%d param=%s (%d samples)", location_id, parameter, len(X))


def detect_anomalies(
    df: pd.DataFrame,
    location_id: int,
    parameter: str,
    who_24h_guideline: float | None = None,
) -> list[dict]:
    """Detect anomalies in recent measurements.

    Returns list of anomaly events with severity classification.
    """
    path = _model_path(location_id, parameter)

    df_feat = build_features(df, target_col="value")
    df_feat = df_feat.dropna(subset=["value", "lag_1h", "roll_mean_6h"])

    if df_feat.empty:
        return []

    anomalies = []

    if path.exists():
        bundle = joblib.load(path)
        detector = bundle["detector"]
        scaler = bundle["scaler"]
        feature_cols = bundle["feature_cols"]

        X = df_feat[feature_cols].fillna(0).values
        X_scaled = scaler.transform(X)
        scores = detector.decision_function(X_scaled)  # negative = anomaly
        predictions = detector.predict(X_scaled)       # -1 = anomaly
    else:
        # Fallback: pure z-score anomaly detection
        vals = df_feat["value"].values
        mean, std = vals.mean(), vals.std() + 1e-9
        z_scores = (vals - mean) / std
        scores = -np.abs(z_scores)   # keep same sign convention as IsolationForest
        predictions = np.where(np.abs(z_scores) > 3, -1, 1)

    for i, (_, row) in enumerate(df_feat.iterrows()):
        if predictions[i] != -1:
            continue

        value = float(row["value"])
        score = float(scores[i])
        who_exc = False
        if who_24h_guideline and value > who_24h_guideline:
            who_exc = True

        # Severity mapping
        if score < -0.4 or (who_24h_guideline and value > 2.0 * who_24h_guideline):
            severity = "critical"
        elif score < -0.3 or (who_24h_guideline and value > 1.5 * who_24h_guideline):
            severity = "high"
        elif score < -0.2 or who_exc:
            severity = "medium"
        else:
            severity = "low"

        anomalies.append({
            "location_id": location_id,
            "detected_at": row["measured_at"],
            "peak_value": value,
            "anomaly_score": score,
            "severity": severity,
            "who_exceedance": who_exc,
        })

    logger.info("Anomaly scan: %d events found for loc=%d param=%s", len(anomalies), location_id, parameter)
    return anomalies
