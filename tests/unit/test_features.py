"""Unit tests for time-series feature engineering."""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from urbanpulse.ml.features import build_features, FEATURE_COLS


def _make_df(n: int = 100, value: float = 20.0) -> pd.DataFrame:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    timestamps = [start + timedelta(hours=i) for i in range(n)]
    return pd.DataFrame({"measured_at": timestamps, "value": [value] * n})


def test_feature_columns_complete():
    df = build_features(_make_df(100))
    for col in FEATURE_COLS:
        assert col in df.columns, f"Missing feature column: {col}"


def test_cyclical_encoding_range():
    df = build_features(_make_df(100))
    assert df["hour_sin"].between(-1.0, 1.0).all()
    assert df["hour_cos"].between(-1.0, 1.0).all()
    assert df["dow_sin"].between(-1.0, 1.0).all()
    assert df["dow_cos"].between(-1.0, 1.0).all()


def test_lag_features_shift_correctly():
    df_in = _make_df(50)
    df_in.loc[0, "value"] = 999.0
    df = build_features(df_in)
    assert df["lag_1h"].iloc[1] == pytest.approx(999.0)


def test_rolling_mean_constant_series():
    df = build_features(_make_df(100, value=10.0)).dropna()
    assert df["roll_mean_3h"].iloc[-1] == pytest.approx(10.0, abs=1e-6)


def test_no_inf_values():
    df = build_features(_make_df(100))
    assert not np.isinf(df.select_dtypes("number").values).any()


def test_measured_at_column_preserved():
    df = build_features(_make_df(50))
    assert "measured_at" in df.columns
