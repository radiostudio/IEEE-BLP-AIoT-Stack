"""Live sensor viewer: pick a sensor, device and field.

In the Docker stack this runs on port 8501 (STREAMLIT_PORT in .env) and
reloads when the file is saved. Outside Docker:

    streamlit run analysis/streamlit_app.py
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import aiot_data

WINDOWS = {"15 minutes": "15m", "1 hour": "1h", "6 hours": "6h", "24 hours": "24h"}

st.set_page_config(page_title="AIoT sensors", layout="wide")
st.title("AIoT sensors")

try:
    devices = aiot_data.sensors("24h")
except Exception as exc:  # InfluxDB down or not reachable
    st.error(f"Cannot read InfluxDB at {aiot_data.INFLUX_URL}: {exc}")
    st.stop()

if devices.empty:
    st.info("No readings in the last 24 hours. Power a sensor node and wait "
            "a few seconds.")
    st.stop()

with st.sidebar:
    uid = st.selectbox("Sensor", devices["sensor_uid"].unique())
    mine = devices[devices["sensor_uid"] == uid]
    macs = list(mine["mac"])
    mac = st.selectbox("Device", ["All"] + macs) if len(macs) > 1 else macs[0]
    st.caption(f"Device ID: {mac}" if mac != "All" else f"{len(macs)} devices")
    fields = sorted({f for fs in mine["fields"] for f in fs})
    field = st.selectbox("Field", fields)
    window = st.radio("Window", list(WINDOWS), index=1)
    st.caption(f"InfluxDB: {aiot_data.INFLUX_URL}, database {aiot_data.INFLUX_DB}")


@st.fragment(run_every="10s")
def live() -> None:
    df = aiot_data.readings(uid, field, None if mac == "All" else mac,
                            WINDOWS[window])
    if df.empty:
        st.warning(f"No {field} readings for {uid} in the last {window}.")
        return

    cols = st.columns(max(1, df["mac"].nunique()))
    for col, (m, d) in zip(cols, df.groupby("mac")):
        last = d.iloc[-1]
        age = (pd.Timestamp.now(tz="UTC") - last["time"]).total_seconds()
        col.metric(f"{uid} {m}", f"{last['value']:.2f}",
                   f"{last['value'] - d['value'].mean():+.2f} vs mean",
                   delta_color="off")
        col.caption(f"{age:.0f} s ago · "
                    + ("sensor ok" if int(last["status"]) & 1 else "SENSOR FAULT"))

    # one line per device; long form, because a MAC as a column name breaks
    # the chart (Altair reads ":" as a type suffix)
    st.line_chart(df, x="time", y="value", color="mac", x_label="",
                  y_label=field)

    stats = df.groupby("mac")["value"].agg(["count", "mean", "min", "max", "std"])
    st.dataframe(stats.round(3))


live()
