"""Feature engineering for time-series air quality forecasting."""

import numpy as np
import pandas as pd


def build_features(df: pd.DataFrame, target_col: str = "value") -> pd.DataFrame:
    """Build feature matrix from a time-indexed measurement DataFrame.

    Args:
        df: DataFrame with columns [measured_at, value] sorted by measured_at.
        target_col: column to build lag features for.

    Returns:
        DataFrame with feature columns added.
    """
    df = df.copy().sort_values("measured_at").reset_index(drop=True)
    df["measured_at"] = pd.to_datetime(df["measured_at"], utc=True)
    df = df.set_index("measured_at")

    val = df[target_col]

    # ── Temporal features ─────────────────────────────────────────────
    df["hour"] = df.index.hour
    df["day_of_week"] = df.index.dayofweek
    df["month"] = df.index.month
    df["is_weekend"] = (df.index.dayofweek >= 5).astype(int)
    df["is_rush_hour"] = df.index.hour.isin([7, 8, 9, 17, 18, 19]).astype(int)
    df["hour_sin"] = np.sin(2 * np.pi * df.index.hour / 24)
    df["hour_cos"] = np.cos(2 * np.pi * df.index.hour / 24)
    df["dow_sin"] = np.sin(2 * np.pi * df.index.dayofweek / 7)
    df["dow_cos"] = np.cos(2 * np.pi * df.index.dayofweek / 7)

    # ── Lag features ─────────────────────────────────────────────────
    for lag in [1, 2, 3, 6, 12, 24, 48]:
        df[f"lag_{lag}h"] = val.shift(lag)

    # ── Rolling statistics ────────────────────────────────────────────
    for window in [3, 6, 12, 24]:
        df[f"roll_mean_{window}h"] = val.shift(1).rolling(window, min_periods=1).mean()
        df[f"roll_std_{window}h"] = val.shift(1).rolling(window, min_periods=1).std().fillna(0)
        df[f"roll_max_{window}h"] = val.shift(1).rolling(window, min_periods=1).max()

    # ── Trend ─────────────────────────────────────────────────────────
    df["delta_1h"] = val.diff(1)
    df["delta_24h"] = val.diff(24)

    return df.reset_index()


FEATURE_COLS = [
    "hour", "day_of_week", "month", "is_weekend", "is_rush_hour",
    "hour_sin", "hour_cos", "dow_sin", "dow_cos",
    "lag_1h", "lag_2h", "lag_3h", "lag_6h", "lag_12h", "lag_24h", "lag_48h",
    "roll_mean_3h", "roll_std_3h", "roll_max_3h",
    "roll_mean_6h", "roll_std_6h", "roll_max_6h",
    "roll_mean_12h", "roll_std_12h", "roll_max_12h",
    "roll_mean_24h", "roll_std_24h", "roll_max_24h",
    "delta_1h", "delta_24h",
]
