"""XGBoost-based pollutant forecasting — trains per (location, parameter) pair."""

import logging
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBRegressor

from urbanpulse.config import settings
from urbanpulse.ml.features import FEATURE_COLS, build_features

logger = logging.getLogger(__name__)

HORIZON_HOURS = 24
MIN_ROWS_TO_TRAIN = 72  # at least 3 days of hourly data


def _model_path(location_id: int, parameter: str) -> Path:
    return settings.models_dir / f"xgb_{location_id}_{parameter}.joblib"


def train(
    df: pd.DataFrame,
    location_id: int,
    parameter: str,
) -> dict:
    """Train an XGBoost model for a (location, parameter) pair.

    Args:
        df: DataFrame with [measured_at, value] columns.
        location_id: DB location ID (used for model file naming).
        parameter: Parameter name, e.g. "pm25".

    Returns:
        Dict with mae, rmse, model_version.
    """
    df_feat = build_features(df, target_col="value")
    df_feat = df_feat.dropna(subset=FEATURE_COLS + ["value"])

    if len(df_feat) < MIN_ROWS_TO_TRAIN:
        raise ValueError(
            f"Insufficient data to train ({len(df_feat)} rows < {MIN_ROWS_TO_TRAIN} required)"
        )

    X = df_feat[FEATURE_COLS].values
    y = df_feat["value"].values

    split = int(len(X) * 0.8)
    X_train, X_val = X[:split], X[split:]
    y_train, y_val = y[:split], y[split:]

    pipe = Pipeline([
        ("scaler", StandardScaler()),
        ("xgb", XGBRegressor(
            n_estimators=300,
            max_depth=6,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            objective="reg:squarederror",
            tree_method="hist",
            n_jobs=-1,
            random_state=42,
            verbosity=0,
        )),
    ])
    pipe.fit(X_train, y_train)

    y_pred = pipe.predict(X_val)
    mae = float(mean_absolute_error(y_val, y_pred))
    rmse = float(np.sqrt(mean_squared_error(y_val, y_pred)))

    path = _model_path(location_id, parameter)
    joblib.dump(pipe, path)

    version = f"xgb_v{int(pd.Timestamp.now().timestamp())}"
    logger.info(
        "Trained %s loc=%d param=%s — MAE=%.3f RMSE=%.3f → %s",
        version, location_id, parameter, mae, rmse, path,
    )
    return {"mae": mae, "rmse": rmse, "model_version": version, "n_train": split}


def predict(
    df_history: pd.DataFrame,
    location_id: int,
    parameter: str,
) -> list[dict]:
    """Generate 24-hour forecast for a (location, parameter) pair.

    Returns list of dicts: {hour_offset, predicted_value, lower_bound, upper_bound}
    """
    path = _model_path(location_id, parameter)
    if not path.exists():
        logger.warning("No model found at %s — cannot predict", path)
        return []

    pipe: Pipeline = joblib.load(path)

    df_feat = build_features(df_history.copy(), target_col="value")
    df_feat = df_feat.dropna(subset=FEATURE_COLS)

    if df_feat.empty:
        return []

    # Use the last row's features as the base for iterative forecasting
    last_row = df_feat.iloc[-1].copy()
    last_ts = pd.Timestamp(last_row["measured_at"]).tz_convert("UTC")
    history_values = df_feat["value"].tolist()

    forecasts = []
    for h in range(1, HORIZON_HOURS + 1):
        future_ts = last_ts + pd.Timedelta(hours=h)

        # Build a synthetic feature row for this future timestamp
        feat_row = _build_future_features(future_ts, history_values)
        X = np.array([feat_row])

        pred = float(max(0, pipe.predict(X)[0]))
        # Simple uncertainty: ±15% as confidence interval
        margin = pred * 0.15
        forecasts.append({
            "predicted_for": future_ts.isoformat(),
            "hour_offset": h,
            "predicted_value": round(pred, 3),
            "lower_bound": round(max(0, pred - margin), 3),
            "upper_bound": round(pred + margin, 3),
        })
        history_values.append(pred)

    return forecasts


def _build_future_features(ts: pd.Timestamp, history: list[float]) -> list[float]:
    """Build a single feature vector for a future timestamp using recent history."""
    from urbanpulse.ml.features import FEATURE_COLS
    import numpy as np

    def lag(n):
        idx = len(history) - n
        return history[idx] if idx >= 0 else np.nan

    def roll_mean(w):
        vals = history[-w:] if len(history) >= w else history
        return float(np.mean(vals)) if vals else np.nan

    def roll_std(w):
        vals = history[-w:] if len(history) >= w else history
        return float(np.std(vals)) if len(vals) > 1 else 0.0

    def roll_max(w):
        vals = history[-w:] if len(history) >= w else history
        return float(np.max(vals)) if vals else np.nan

    delta_1h = (history[-1] - history[-2]) if len(history) >= 2 else 0.0
    delta_24h = (history[-1] - history[-25]) if len(history) >= 25 else 0.0

    return [
        ts.hour, ts.dayofweek, ts.month,
        int(ts.dayofweek >= 5), int(ts.hour in [7, 8, 9, 17, 18, 19]),
        np.sin(2 * np.pi * ts.hour / 24), np.cos(2 * np.pi * ts.hour / 24),
        np.sin(2 * np.pi * ts.dayofweek / 7), np.cos(2 * np.pi * ts.dayofweek / 7),
        lag(1), lag(2), lag(3), lag(6), lag(12), lag(24), lag(48),
        roll_mean(3), roll_std(3), roll_max(3),
        roll_mean(6), roll_std(6), roll_max(6),
        roll_mean(12), roll_std(12), roll_max(12),
        roll_mean(24), roll_std(24), roll_max(24),
        delta_1h, delta_24h,
    ]
