"""EU Common Air Quality Index (CAQI) computation — official EU standard."""

from dataclasses import dataclass

# EU CAQI breakpoints per pollutant (µg/m³)
# Source: https://www.airqualitynow.eu/about_indices_definition.php
_PM25_BREAKS  = [0, 15, 30, 55, 110]
_PM10_BREAKS  = [0, 25, 50, 90, 180]
_NO2_BREAKS   = [0, 50, 100, 200, 400]
_O3_BREAKS    = [0, 60, 120, 180, 240]

CAQI_BANDS = [
    (0,   25,  "Very Low",  "#79BC6A", "Air quality is good."),
    (25,  50,  "Low",       "#BBCF4C", "Air quality is acceptable."),
    (50,  75,  "Medium",    "#EEC20B", "Sensitive groups may be affected."),
    (75,  100, "High",      "#F29305", "Everyone may begin to experience health effects."),
    (100, 999, "Very High", "#E8416F", "Health warnings of emergency conditions."),
]


@dataclass
class CaqiResult:
    caqi: float
    band: str
    color: str
    message: str
    pm25_sub: float | None
    pm10_sub: float | None
    no2_sub: float | None
    o3_sub: float | None


def compute_caqi(
    pm25: float | None = None,
    pm10: float | None = None,
    no2: float | None = None,
    o3: float | None = None,
) -> CaqiResult:
    """Compute the EU CAQI index from hourly pollutant concentrations.

    The CAQI is the maximum sub-index across available pollutants.
    """
    sub_indices = {}
    if pm25 is not None:
        sub_indices["pm25"] = _linear_interpolate(pm25, _PM25_BREAKS)
    if pm10 is not None:
        sub_indices["pm10"] = _linear_interpolate(pm10, _PM10_BREAKS)
    if no2 is not None:
        sub_indices["no2"] = _linear_interpolate(no2, _NO2_BREAKS)
    if o3 is not None:
        sub_indices["o3"] = _linear_interpolate(o3, _O3_BREAKS)

    if not sub_indices:
        caqi = 0.0
    else:
        caqi = max(sub_indices.values())

    caqi = min(round(caqi, 1), 100.0)
    band, color, message = _get_band(caqi)

    return CaqiResult(
        caqi=caqi,
        band=band,
        color=color,
        message=message,
        pm25_sub=sub_indices.get("pm25"),
        pm10_sub=sub_indices.get("pm10"),
        no2_sub=sub_indices.get("no2"),
        o3_sub=sub_indices.get("o3"),
    )


def _linear_interpolate(value: float, breaks: list[float]) -> float:
    """Map a concentration value to 0–100 CAQI sub-index."""
    caqi_breaks = [0, 25, 50, 75, 100]
    value = max(0, value)
    for i in range(len(breaks) - 1):
        if breaks[i] <= value <= breaks[i + 1]:
            ratio = (value - breaks[i]) / (breaks[i + 1] - breaks[i])
            return caqi_breaks[i] + ratio * (caqi_breaks[i + 1] - caqi_breaks[i])
    return 100.0  # above highest breakpoint


def _get_band(caqi: float) -> tuple[str, str, str]:
    for lo, hi, band, color, msg in CAQI_BANDS:
        if lo <= caqi < hi:
            return band, color, msg
    return "Very High", "#E8416F", "Health warnings of emergency conditions."
