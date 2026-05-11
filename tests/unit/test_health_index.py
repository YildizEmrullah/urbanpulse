"""Unit tests for EU CAQI health index computation."""

import pytest
from urbanpulse.ml.health_index import compute_caqi, CaqiResult


def test_very_low_band():
    result = compute_caqi(pm25=3.0, pm10=10.0, no2=5.0, o3=20.0)
    assert isinstance(result, CaqiResult)
    assert result.band == "Very Low"
    assert result.caqi < 25
    assert result.color == "#79BC6A"


def test_high_band_pm25():
    # PM2.5=80µg/m³ is above the 55µg breakpoint → CAQI > 75 → "High" or "Very High"
    result = compute_caqi(pm25=80.0, pm10=5.0, no2=5.0, o3=20.0)
    assert result.band in ("High", "Very High")
    assert result.caqi >= 75


def test_missing_pollutants_returns_result():
    result = compute_caqi(pm25=None, pm10=None, no2=None, o3=None)
    assert isinstance(result, CaqiResult)
    assert result.caqi == 0


def test_partial_pollutants():
    result = compute_caqi(pm25=15.0, pm10=None, no2=None, o3=None)
    assert result.caqi > 0


def test_very_high_emergency():
    result = compute_caqi(pm25=120.0, pm10=200.0, no2=200.0, o3=240.0)
    assert result.band == "Very High"
    assert result.caqi >= 100
    assert result.color == "#E8416F"


def test_caqi_sub_indices():
    result = compute_caqi(pm25=10.0, pm10=20.0, no2=15.0, o3=50.0)
    assert result.pm25_sub is not None
    assert result.pm10_sub is not None
    assert result.no2_sub is not None
    assert result.o3_sub is not None


def test_message_non_empty():
    result = compute_caqi(pm25=30.0)
    assert isinstance(result.message, str)
    assert len(result.message) > 0
