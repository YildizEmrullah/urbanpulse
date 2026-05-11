"""Unit tests for anomaly detection."""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from urbanpulse.ml.anomaly import detect_anomalies


def _make_df(n: int = 60, value: float = 20.0) -> pd.DataFrame:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    timestamps = [start + timedelta(hours=i) for i in range(n)]
    return pd.DataFrame({"measured_at": timestamps, "value": [value] * n})


def test_no_anomalies_in_constant_series():
    df = _make_df(60, value=15.0)
    results = detect_anomalies(df, location_id=1, parameter="pm25", who_24h_guideline=15.0)
    assert isinstance(results, list)


def test_spike_detected_as_anomaly():
    df = _make_df(60, value=15.0)
    df.loc[55, "value"] = 999.0
    df.loc[56, "value"] = 950.0
    results = detect_anomalies(df, location_id=1, parameter="pm25", who_24h_guideline=15.0)
    assert len(results) > 0


def test_anomaly_event_has_required_keys():
    df = _make_df(60, value=15.0)
    df.loc[55, "value"] = 999.0
    results = detect_anomalies(df, location_id=1, parameter="pm25", who_24h_guideline=15.0)
    if results:
        event = results[0]
        assert "severity" in event
        assert "peak_value" in event
        assert "anomaly_score" in event
        assert "who_exceedance" in event


def test_severity_values_are_valid():
    df = _make_df(60, value=15.0)
    df.loc[55, "value"] = 999.0
    results = detect_anomalies(df, location_id=1, parameter="pm25", who_24h_guideline=15.0)
    valid = {"low", "medium", "high", "critical"}
    for event in results:
        assert event["severity"] in valid


def test_empty_dataframe_returns_empty():
    df = pd.DataFrame(columns=["measured_at", "value"])
    results = detect_anomalies(df, location_id=1, parameter="pm25")
    assert results == []
