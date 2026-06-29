"""UrbanPulse Streamlit dashboard — 5-page air quality intelligence app."""

import os
import streamlit as st

st.set_page_config(
    page_title="UrbanPulse | Air Quality Intelligence",
    page_icon="🌍",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_resource(show_spinner="Setting up demo data...")
def _seed_if_needed():
    """Seed SQLite demo data on first run (skipped for PostgreSQL)."""
    db_url = os.getenv("DATABASE_URL", "")
    if "postgresql" in db_url:
        return "postgresql-mode"
    import sqlite3, subprocess, sys
    from pathlib import Path
    for candidate in [Path("urbanpulse.db"), Path(__file__).parents[3] / "urbanpulse.db"]:
        try:
            if candidate.exists():
                conn = sqlite3.connect(str(candidate))
                count = conn.execute("SELECT COUNT(*) FROM fact_measurement").fetchone()[0]
                conn.close()
                if count > 0:
                    return count
        except Exception:
            pass
    subprocess.run([sys.executable, "scripts/seed_demo_data.py"], check=False)
    return "seeded"


_seed_if_needed()

from urbanpulse.dashboard import api_client as api


def _render_map():
    import folium
    import pandas as pd
    from streamlit_folium import st_folium

    st.header("🗺️ European Air Quality Map")
    st.caption("Real-time monitoring stations — bubble size = PM2.5, color = CAQI band")
    with st.expander("ℹ️ About this page", expanded=False):
        st.markdown("""
        **What you're seeing:** Live air quality readings from OpenAQ monitoring stations
        across 15 European cities. Each bubble represents one city.

        - **Bubble color** → EU Common Air Quality Index (CAQI) band
        - **Click a bubble** → see current CAQI score and pollution level
        - **Data refresh** → ingested automatically every 60 minutes via APScheduler

        **CAQI** is the official EU air quality standard used by the European Environment Agency.
        It aggregates PM2.5, PM10, NO₂ and O₃ into a single 0–100 index.
        Lower is cleaner. Above 75 is considered unhealthy for sensitive groups.
        """)

    ranking_data = api.get_health_ranking()
    if "error" in ranking_data:
        st.error(f"API unavailable: {ranking_data['error']}\n\nStart the API: `uvicorn urbanpulse.api.main:app --reload`")
        return

    locs_data = api.get_locations()
    if not locs_data.get("results"):
        st.info("No station data yet. The API is seeding data — check back in a moment.")
        return

    city_caqi = {r["city"]: r for r in ranking_data.get("ranking", [])}
    city_color = {"Very Low": "#79BC6A", "Low": "#BBCF4C", "Medium": "#EEC20B",
                  "High": "#F29305", "Very High": "#E8416F"}

    m = folium.Map(location=[51.5, 10.0], zoom_start=5, tiles="CartoDB positron")

    seen_cities = set()
    for loc in locs_data["results"]:
        city = loc.get("city")
        lat, lon = loc.get("latitude"), loc.get("longitude")
        if not lat or not lon or city in seen_cities:
            continue
        seen_cities.add(city)
        caqi_info = city_caqi.get(city, {})
        color = city_color.get(caqi_info.get("band", ""), "#888888")
        caqi_val = caqi_info.get("caqi", "N/A")
        band = caqi_info.get("band", "No data")

        folium.CircleMarker(
            location=[lat, lon],
            radius=max(6, min(20, float(caqi_val) / 5)) if isinstance(caqi_val, (int, float)) else 8,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.7,
            popup=folium.Popup(f"<b>{city}</b><br>CAQI: {caqi_val}<br>Band: {band}", max_width=200),
            tooltip=f"{city}: {band}",
        ).add_to(m)

    col1, col2 = st.columns([3, 1])
    with col1:
        st_folium(m, height=500, use_container_width=True)
    with col2:
        st.markdown("**CAQI Legend**")
        for band, color in city_color.items():
            st.markdown(
                f"<div style='display:flex;align-items:center;gap:8px;margin:4px 0'>"
                f"<span style='width:16px;height:16px;background:{color};display:inline-block;border-radius:3px'></span>"
                f"<span>{band}</span></div>",
                unsafe_allow_html=True,
            )


def _render_timeseries():
    import plotly.graph_objects as go
    import pandas as pd
    from datetime import datetime, timedelta, timezone

    st.header("📈 Pollutant Time Series")
    with st.expander("ℹ️ About this page", expanded=False):
        st.markdown("""
        **What you're seeing:** Hourly-aggregated pollutant concentrations stored in a
        star-schema data warehouse (SQLite/PostgreSQL via SQLAlchemy 2.0).

        - **Blue line** → hourly average concentration
        - **Red dotted line** → daily maximum
        - **Red dashed threshold** → WHO 2021 Air Quality Guideline for 24-hour exposure

        **WHO Guidelines used:** PM2.5 = 15 µg/m³ · PM10 = 45 µg/m³ · NO₂ = 25 µg/m³ · O₃ = 100 µg/m³

        Select any city, pollutant, and time window. The chart updates live from the database.
        """)

    locs_data = api.get_locations()
    if "error" in locs_data or not locs_data.get("results"):
        st.error("No data available. Ensure the API and ingestion pipeline are running.")
        return

    cities = sorted(set(l["city"] for l in locs_data["results"] if l.get("city")))
    col1, col2, col3 = st.columns(3)
    with col1:
        selected_city = st.selectbox("City", cities)
    with col2:
        parameter = st.selectbox("Pollutant", ["pm25", "pm10", "no2", "o3", "so2", "co"])
    with col3:
        days_back = st.slider("Days back", 1, 30, 7)

    city_locs = [l for l in locs_data["results"] if l.get("city") == selected_city]
    if not city_locs:
        st.warning(f"No stations found in {selected_city}")
        return

    loc_id = city_locs[0]["location_id"]
    date_to = datetime.now(timezone.utc)
    date_from = date_to - timedelta(days=days_back)

    data = api.get_measurements(loc_id, parameter, date_from, date_to, aggregation="hourly")
    if "error" in data or not data.get("results"):
        st.warning("No measurements available for this selection.")
        return

    df = pd.DataFrame(data["results"])
    df["bucket"] = pd.to_datetime(df["bucket"])

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["bucket"], y=df["avg"],
        mode="lines", name=f"{parameter.upper()} (avg)",
        line=dict(color="#3d9bde", width=2),
        fill="tozeroy", fillcolor="rgba(61,155,222,0.08)",
    ))
    fig.add_trace(go.Scatter(
        x=df["bucket"], y=df["max"],
        mode="lines", name="Max", line=dict(color="#e05c5c", width=1, dash="dot"),
    ))

    who_guideline = data.get("who_24h_guideline")
    if who_guideline:
        fig.add_hline(
            y=who_guideline, line_dash="dash", line_color="red",
            annotation_text=f"WHO 24h guideline: {who_guideline} µg/m³",
            annotation_position="top right",
        )

    fig.update_layout(
        title=f"{parameter.upper()} — {selected_city} (hourly avg, last {days_back}d)",
        xaxis_title="Time (UTC)",
        yaxis_title="Concentration (µg/m³)",
        template="plotly_white",
        height=450,
    )
    st.plotly_chart(fig, use_container_width=True)

    m1, m2, m3 = st.columns(3)
    m1.metric("Average", f"{df['avg'].mean():.2f} µg/m³")
    m2.metric("Peak", f"{df['max'].max():.2f} µg/m³")
    m3.metric("WHO exceedances", int((df["max"] > who_guideline).sum()) if who_guideline else "N/A")


def _render_forecast():
    import plotly.graph_objects as go
    import pandas as pd
    from datetime import datetime, timedelta, timezone

    st.header("🔮 24-Hour Air Quality Forecast")
    st.caption("XGBoost model trained on historical lag features + temporal patterns")
    with st.expander("ℹ️ About this page", expanded=False):
        st.markdown("""
        **What you're seeing:** A 24-hour ahead forecast generated by an XGBoost regression model
        trained separately for each (city, pollutant) pair.

        **Feature engineering (30 features):**
        - Lag values: 1h, 2h, 3h, 6h, 12h, 24h, 48h
        - Rolling statistics: mean, std, max over 3h / 6h / 12h / 24h windows
        - Temporal: hour-of-day, day-of-week, month, weekend flag, rush-hour flag
        - Cyclical encodings: sin/cos of hour and weekday (prevents discontinuity at midnight)
        - Trend: Δ1h, Δ24h (first differences)

        **Confidence band** = ±15% of predicted value. Models auto-retrain every 24 hours.
        Click *Trigger new forecast* to generate predictions immediately.
        """)

    locs_data = api.get_locations()
    if "error" in locs_data or not locs_data.get("results"):
        st.error("API unavailable.")
        return

    cities = sorted(set(l["city"] for l in locs_data["results"] if l.get("city")))
    col1, col2 = st.columns(2)
    with col1:
        selected_city = st.selectbox("City", cities)
    with col2:
        parameter = st.selectbox("Pollutant", ["pm25", "pm10", "no2", "o3"])

    city_locs = [l for l in locs_data["results"] if l.get("city") == selected_city]
    if not city_locs:
        return
    loc_id = city_locs[0]["location_id"]

    if st.button("🔄 Trigger new forecast"):
        import httpx, os
        API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000/api/v1")
        with httpx.Client(timeout=30) as c:
            r = c.post(f"{API_BASE}/predictions/trigger", params={"location_id": loc_id, "parameter": parameter})
        st.success("Forecast job queued! Refresh in ~30 seconds.")

    pred_data = api.get_predictions(loc_id, parameter)
    hist_data = api.get_measurements(loc_id, parameter, aggregation="hourly")

    fig = go.Figure()

    if hist_data.get("results"):
        hist_df = pd.DataFrame(hist_data["results"])
        hist_df["bucket"] = pd.to_datetime(hist_df["bucket"])
        hist_df = hist_df.tail(48)
        fig.add_trace(go.Scatter(
            x=hist_df["bucket"], y=hist_df["avg"],
            mode="lines", name="Historical (48h)",
            line=dict(color="#3d9bde", width=2),
        ))

    if pred_data.get("forecasts"):
        fc_df = pd.DataFrame(pred_data["forecasts"])
        fc_df["predicted_for"] = pd.to_datetime(fc_df["predicted_for"])
        fig.add_trace(go.Scatter(
            x=fc_df["predicted_for"], y=fc_df["predicted_value"],
            mode="lines+markers", name="Forecast (24h)",
            line=dict(color="#f5a623", width=2, dash="dash"),
        ))
        if "upper_bound" in fc_df.columns and "lower_bound" in fc_df.columns:
            fig.add_traces([
                go.Scatter(x=fc_df["predicted_for"], y=fc_df["upper_bound"],
                           mode="lines", showlegend=False, line=dict(width=0)),
                go.Scatter(x=fc_df["predicted_for"], y=fc_df["lower_bound"],
                           mode="lines", fill="tonexty",
                           fillcolor="rgba(245,166,35,0.15)", showlegend=False, line=dict(width=0)),
            ])
        model_ver = pred_data.get("forecasts", [{}])[0].get("model_version", "N/A")
        mae = pred_data.get("forecasts", [{}])[0].get("mae")
        st.info(f"Model: `{model_ver}` | MAE: {f'{mae:.3f} µg/m³' if mae else 'N/A'}")
    else:
        st.warning("No forecast available. Click 'Trigger new forecast' to generate one.")

    fig.update_layout(
        title=f"{parameter.upper()} Forecast — {selected_city}",
        xaxis_title="Time (UTC)", yaxis_title="µg/m³",
        template="plotly_white", height=420,
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_anomalies():
    import plotly.graph_objects as go
    import pandas as pd

    st.header("⚠️ Pollution Anomaly Events")
    st.caption("Detected by IsolationForest ensemble — z-score fallback if model not trained")
    with st.expander("ℹ️ About this page", expanded=False):
        st.markdown("""
        **What you're seeing:** Unusual pollution spikes detected by an unsupervised ML model
        running on a 30-minute scan schedule.

        **Detection method:** IsolationForest (sklearn, 200 estimators, 5% contamination).
        Falls back to z-score > 3σ when the model hasn't been trained yet.

        **Severity classification:**
        | Severity | Condition |
        |----------|-----------|
        | 🔴 Critical | Anomaly score < −0.4 **or** value > 2× WHO daily limit |
        | 🟠 High | Score < −0.3 **or** value > 1.5× WHO limit |
        | 🟡 Medium | Score < −0.2 **or** any WHO exceedance |
        | 🟢 Low | Flagged by model but within WHO limits |

        Each dot on the timeline is one detected event. Hover for details.
        """)

    summary = api.get_anomaly_summary()
    if summary.get("summary"):
        sev_data = summary["summary"]
        cols = st.columns(4)
        for i, sev in enumerate(["critical", "high", "medium", "low"]):
            count = sev_data.get(sev, 0)
            colors = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}
            cols[i].metric(f"{colors[sev]} {sev.title()}", count)

    col1, col2 = st.columns(2)
    with col1:
        severity_filter = st.selectbox("Severity filter", ["All", "critical", "high", "medium", "low"])
    with col2:
        days = st.slider("Days back", 1, 90, 30)

    from datetime import datetime, timedelta, timezone
    date_to = datetime.now(timezone.utc)
    date_from = date_to - timedelta(days=days)
    sev = None if severity_filter == "All" else severity_filter
    data = api.get_anomalies(severity=sev, date_from=date_from, date_to=date_to)

    if "error" in data or not data.get("results"):
        st.info("No anomaly events found for this selection.")
        return

    df = pd.DataFrame(data["results"])
    df["detected_at"] = pd.to_datetime(df["detected_at"])

    sev_colors = {"critical": "#e8416f", "high": "#f29305", "medium": "#eec20b", "low": "#79bc6a"}
    df["color"] = df["severity"].map(sev_colors).fillna("#888")

    fig = go.Figure(go.Scatter(
        x=df["detected_at"],
        y=df["peak_value"].fillna(0),
        mode="markers",
        marker=dict(color=df["color"], size=8, opacity=0.8),
        text=df["severity"],
        hovertemplate="<b>%{text}</b><br>Value: %{y:.1f}<br>%{x}<extra></extra>",
    ))
    fig.update_layout(title="Anomaly Events Timeline", xaxis_title="Time", yaxis_title="Peak Value (µg/m³)",
                      template="plotly_white", height=380)
    st.plotly_chart(fig, use_container_width=True)

    with st.expander(f"View all {len(df)} events"):
        st.dataframe(df[["detected_at", "location_id", "severity", "peak_value", "who_exceedance"]], use_container_width=True)


def _render_ranking():
    import plotly.graph_objects as go
    import pandas as pd

    st.header("🏆 City Health Index Ranking")
    st.caption("EU Common Air Quality Index (CAQI) — lower = cleaner air")
    with st.expander("ℹ️ About this page", expanded=False):
        st.markdown("""
        **What you're seeing:** All monitored cities ranked by their current EU CAQI score,
        computed from the last hour's average pollutant concentrations.

        **EU CAQI** (Common Air Quality Index) is the official standard used across
        European cities for public air quality communication. It is computed as the
        **maximum sub-index** across PM2.5, PM10, NO₂ and O₃ using piecewise linear
        interpolation between official EU breakpoints.

        | Band | CAQI | Meaning |
        |------|------|---------|
        | 🟢 Very Low | 0–25 | Air quality is good |
        | 🟡 Low | 25–50 | Acceptable |
        | 🟠 Medium | 50–75 | Sensitive groups may be affected |
        | 🔴 High | 75–100 | Health effects for everyone |
        | ⛔ Very High | 100+ | Emergency health conditions |

        Rankings update automatically every 60 minutes when new measurements arrive.
        """)

    data = api.get_health_ranking()
    if "error" in data or not data.get("ranking"):
        st.info("No data available. The API may still be ingesting initial data.")
        return

    df = pd.DataFrame(data["ranking"])
    df = df.sort_values("caqi")

    col1, col2 = st.columns([2, 1])
    with col1:
        fig = go.Figure(go.Bar(
            x=df["caqi"],
            y=df["city"],
            orientation="h",
            marker_color=df["color"],
            text=df["caqi"].round(1),
            textposition="outside",
        ))
        fig.update_layout(
            title="Cities by CAQI Score (current hour)", xaxis_title="CAQI (0–100)",
            template="plotly_white", height=max(350, len(df) * 28),
            xaxis=dict(range=[0, 110]),
        )
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.markdown("**City Index Table**")
        band_emoji = {"Very Low": "🟢", "Low": "🟡", "Medium": "🟠", "High": "🔴", "Very High": "⛔"}
        for _, row in df.iterrows():
            emoji = band_emoji.get(row["band"], "⚪")
            st.markdown(f"{emoji} **{row['city']}** — {row['caqi']:.0f} ({row['band']})")

    st.caption(f"Last updated: {data.get('computed_at', 'N/A')}")


# ── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("🌍 UrbanPulse")
    st.caption("European Air Quality Intelligence")
    st.markdown("""
    Real-time air quality monitoring, forecasting and anomaly detection for 15 European cities.

    **Stack:** FastAPI · SQLAlchemy · XGBoost · IsolationForest · APScheduler · Streamlit
    **Data:** OpenAQ v3 · EU CAQI standard
    """)

    health = api.get_api_health()
    status_color = "🟢" if health.get("status") == "ok" else "🔴"
    st.markdown(f"**API:** {status_color} {health.get('status', 'unknown')}")
    st.divider()

    page = st.radio("Navigate", [
        "🗺️ City Map",
        "📈 Time Series",
        "🔮 24h Forecast",
        "⚠️ Anomalies",
        "🏆 Health Ranking",
    ])
    st.divider()
    st.caption("Data: OpenAQ · Open-Meteo\nModel: EU CAQI · XGBoost · IsolationForest")


# ── Page dispatcher ──────────────────────────────────────────────────────────
if page == "🗺️ City Map":
    _render_map()
elif page == "📈 Time Series":
    _render_timeseries()
elif page == "🔮 24h Forecast":
    _render_forecast()
elif page == "⚠️ Anomalies":
    _render_anomalies()
elif page == "🏆 Health Ranking":
    _render_ranking()
