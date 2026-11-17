"""Live sensor viewer: pick a sensor, device and field.

This is a Streamlit app. Streamlit turns a Python script into a web page:
every st.something(...) line puts something on the page (a title, a
dropdown, a chart). When the user changes a dropdown, Streamlit runs the
whole script again from the top, with the new choice.

In the Docker stack this page is at http://<gateway-ip>:8501/ and it
reloads by itself when you save this file. Outside Docker:

    streamlit run analysis/streamlit_app.py
"""

# --- Libraries ---------------------------------------------------------------
import pandas as pd             # tables, and time calculations
import streamlit as st          # the web page

import aiot_data                # our helper that reads InfluxDB (aiot_data.py)

# The choices shown under "Window", and the InfluxDB duration for each:
# "15m" = 15 minutes, "1h" = 1 hour, "24h" = 24 hours.
WINDOWS = {
    "15 minutes": "15m",
    "1 hour": "1h",
    "6 hours": "6h",
    "24 hours": "24h",
}

# The browser tab title, and a page that uses the full width of the screen
st.set_page_config(page_title="AIoT sensors", layout="wide")

# The big heading at the top of the page
st.title("AIoT sensors")


# --- 1. Which devices have sent data? ----------------------------------------
# try / except: if reading the database fails, show a red message instead of
# crashing.
try:
    devices = aiot_data.sensors("24h")      # one row per device, last 24 hours
except Exception as error:
    # InfluxDB is not running or cannot be reached
    st.error(f"Cannot read InfluxDB at {aiot_data.INFLUX_URL}: {error}")
    st.stop()                               # stop here: nothing else to show

# .empty is True when the table has no rows
if devices.empty:
    st.info("No readings in the last 24 hours. Power a sensor node and wait "
            "a few seconds.")
    st.stop()


# --- 2. The choices in the sidebar (the panel on the left) -------------------
# Everything inside "with st.sidebar:" is placed in the sidebar.
with st.sidebar:
    # A dropdown with every sensor ID. .unique() removes repeats: a sensor
    # with two devices appears twice in the table but once in the dropdown.
    # selectbox returns what the user picked, e.g. "1:1".
    uid = st.selectbox("Sensor", devices["sensor_uid"].unique())

    # The rows of the chosen sensor only (usually one device, sometimes more).
    # devices["sensor_uid"] == uid gives True/False for every row;
    # devices[...] keeps only the rows that are True.
    sensor_devices = devices[devices["sensor_uid"] == uid]
    macs = list(sensor_devices["mac"])      # their Device IDs, as a list

    # Show a Device dropdown only when the sensor has more than one device.
    if len(macs) > 1:
        mac = st.selectbox("Device", ["All"] + macs)
    else:
        mac = macs[0]                       # only one device: use it

    # A small grey line under the choices
    if mac == "All":
        st.caption(f"{len(macs)} devices")
    else:
        st.caption(f"Device ID: {mac}")

    # Collect every field the devices of this sensor report, without repeats.
    # "fields" holds a list per device, so we loop over the lists, then over
    # the names in each list.
    fields = []
    for device_fields in sensor_devices["fields"]:
        for name in device_fields:
            if name not in fields:
                fields.append(name)
    fields.sort()                           # A to Z

    field = st.selectbox("Field", fields)

    # Radio buttons for the time window; index=1 selects "1 hour" at start
    # (index counts from 0: 0 = "15 minutes", 1 = "1 hour", ...)
    window = st.radio("Window", list(WINDOWS), index=1)

    st.caption(f"InfluxDB: {aiot_data.INFLUX_URL}, database {aiot_data.INFLUX_DB}")


# --- 3. The values, chart and table ------------------------------------------
# @st.fragment(run_every="10s") makes this function a "fragment": Streamlit
# runs it again every 10 seconds by itself, so the numbers and the chart stay
# live without reloading the whole page.
@st.fragment(run_every="10s")
def live():
    # "All" means every device of the sensor; aiot_data.readings() wants
    # None for that.
    if mac == "All":
        chosen_mac = None
    else:
        chosen_mac = mac

    # Read the readings: a table with the columns time, mac, value, status
    df = aiot_data.readings(uid, field, chosen_mac, WINDOWS[window])
    if df.empty:
        st.warning(f"No {field} readings for {uid} in the last {window}.")
        return                              # leave the function: nothing to draw

    # --- One box per device with its latest value ---
    # st.columns(n) splits the page width into n columns, side by side.
    device_count = df["mac"].nunique()      # how many different devices
    columns = st.columns(device_count)
    position = 0                            # which column to fill next

    # groupby("mac") splits the table into one smaller table per device.
    # Each loop round gives the Device ID and that device's rows.
    for device_mac, device_df in df.groupby("mac"):
        box = columns[position]
        position = position + 1

        latest = device_df.iloc[-1]         # the last row = the newest reading
        mean = device_df["value"].mean()    # the average over the window
        difference = latest["value"] - mean

        # How many seconds ago was the newest reading taken?
        now = pd.Timestamp.now(tz="UTC")
        age_s = (now - latest["time"]).total_seconds()

        # The status is a number whose bits are flags. "& 1" keeps only
        # bit 0, which the sensor sets to 1 when it is working correctly.
        if int(latest["status"]) & 1:
            health = "sensor ok"
        else:
            health = "SENSOR FAULT"

        # metric(label, value, delta) shows a big number with a small
        # change under it. :.2f = 2 decimals; :+.2f = with a + or - sign.
        # delta_color="off" keeps the change grey (no green/red).
        box.metric(f"{uid} {device_mac}", f"{latest['value']:.2f}",
                   f"{difference:+.2f} vs mean", delta_color="off")
        box.caption(f"{age_s:.0f} s ago · {health}")

    # --- The chart: one line per device ---
    # x = the column for the horizontal axis, y = for the vertical axis,
    # color = one line (and colour) per value of that column.
    # The table stays "long" (one row per reading). Do not turn the MACs into
    # column names: the chart library reads ":" in a column name as a special
    # marker, and the chart would fail.
    st.line_chart(df, x="time", y="value", color="mac", x_label="",
                  y_label=field)

    # --- A table of statistics per device ---
    # groupby("mac")["value"] = the values of each device;
    # .agg([...]) computes these numbers for each device:
    #   count = number of readings, mean = average, min, max,
    #   std = standard deviation (how much the values spread out)
    stats = df.groupby("mac")["value"].agg(["count", "mean", "min", "max", "std"])
    st.dataframe(stats.round(3))            # round to 3 decimals


# Run the fragment once now; after that it runs again every 10 seconds.
live()
