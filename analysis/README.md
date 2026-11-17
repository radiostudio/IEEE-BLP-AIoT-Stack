# Analysis: notebooks and Streamlit apps

This folder is shared by two web apps on the gateway machine:

| App | Address | What for |
|---|---|---|
| JupyterLab | `http://<gateway-ip>:8888/` (ask for the token) | notebooks, and editing files in this folder |
| Streamlit | `http://<gateway-ip>:8501/` | web apps that show sensor data |

What is here:

- `aiot_data.py`: reads the sensor data from InfluxDB into pandas. Use it in
  your notebooks and apps; it already knows where the database is.
- `example.ipynb`: a worked example. Open it in JupyterLab and run it
  (Run, Run All Cells).
- `streamlit_app.py`: the app you see on port 8501.
- `pages/`: your own Streamlit apps (see the exercise below).

To open this file nicely in JupyterLab: right-click `README.md`, Open With,
Markdown Preview.

---

## Exercise: your first Streamlit app

You write a Python script in JupyterLab, and Streamlit turns it into a web
page. Every script in the `pages` folder, next to `streamlit_app.py`,
becomes its own page in the Streamlit sidebar. No restart is needed.

### 1. Open the `pages` folder

In JupyterLab, make sure the file browser on the left shows this folder
(`aiot_data.py`, `example.ipynb`, `pages`, ...). Double-click `pages` to open
it. It is empty at first.

Use this `pages` folder; do not create a new one. Streamlit only watches a
`pages` folder that existed when it started (see "If something goes wrong").

### 2. Create your script

Inside `pages`, **File, New, Python File**. Right-click the new file
(`untitled.py`), **Rename**, and call it `my_app.py`.

If several students share one gateway, add your name, e.g.
`my_app_priya.py`: each file becomes its own page.

### 3. Write the app

Paste this into `my_app.py` and save with **Ctrl+S**:

```python
# --- Libraries ---
import streamlit as st          # turns this script into a web page
import aiot_data                # our helper that reads the sensor database

# The big heading at the top of the page
st.title("My first sensor app")

# --- Which devices are online? ---
# A table (pandas DataFrame) with one row per device that sent data in the
# last hour. Columns: sensor_uid (sensor ID), mac (Device ID), fields (what
# it measures), last (its latest values).
devices = aiot_data.sensors("1h")

# .empty is True when the table has no rows
if devices.empty:
    st.warning("No sensor has sent data in the last hour.")
    st.stop()                   # stop here: nothing else to show

# st.write shows text; len(devices) is the number of rows
st.write(f"{len(devices)} devices online")

# Show three of the columns as a table on the page
st.dataframe(devices[["sensor_uid", "mac", "fields"]])

# --- Choose a sensor ---
# A dropdown with every sensor ID. .unique() removes repeats (a sensor with
# two devices has two rows). It returns what the user picked, e.g. "1:1".
uid = st.selectbox("Sensor", devices["sensor_uid"].unique())

# The rows of the chosen sensor only:
# devices["sensor_uid"] == uid gives True or False for every row, and
# devices[...] keeps the rows that are True.
sensor_rows = devices[devices["sensor_uid"] == uid]

# Its first row (.iloc[0] = row number 0), and the field names in it
first_row = sensor_rows.iloc[0]
fields = first_row["fields"]

# --- Choose a field ---
field = st.selectbox("Field", fields)

# --- Read and show the data ---
# A table with the columns time, mac, value, status: every reading of this
# field in the last hour
df = aiot_data.readings(uid, field, within="1h")

# A line chart: time across, value up, one line per device (color="mac")
st.line_chart(df, x="time", y="value", color="mac")

# The average of all values; :.2f shows it with 2 decimals
average = df["value"].mean()
st.metric("Average", f"{average:.2f}")
```

What each part does:

| Code | Shows |
|---|---|
| `st.title(...)` | the heading |
| `aiot_data.sensors("1h")` | a table of devices (sensor ID, Device ID / MAC, fields) |
| `st.stop()` | ends the page here when there is no data |
| `st.dataframe(...)` | that table, sortable |
| `devices[devices["sensor_uid"] == uid]` | only the rows of the chosen sensor |
| `st.selectbox(...)` | a dropdown; returns what the user picked |
| `aiot_data.readings(...)` | the readings of one field: time, mac, value, status |
| `st.line_chart(...)` | one line per device (`color="mac"`) |
| `st.metric(...)` | a big number |

### 4. Open it

Go to `http://<gateway-ip>:8501/` and refresh the page (F5). The sidebar on
the left now lists **streamlit app** and **my app**. Click **my app**.

Pick another sensor or field: the page updates.

### 5. Change it

Change something, e.g. the title, and save (Ctrl+S). The page in the browser
reloads with your change. Ideas:

- Show the last hour as a table: `st.dataframe(df)`
- Show the maximum:

  ```python
  maximum = df["value"].max()
  st.metric("Max", f"{maximum:.2f}")
  ```
- A longer window: `within="6h"` (any InfluxDB duration: `15m`, `1h`, `24h`, `7d`)
- Only one device: `aiot_data.readings(uid, field, mac="44:1D:64:C1:34:32")`

## How Streamlit runs your script

- The whole script runs from top to bottom every time someone opens the page
  or changes a dropdown. You do not write a loop.
- An error shows in red on the page, with the line number. Fix it, save, and
  the page updates.
- `st.write`, `st.dataframe`, `st.line_chart`, `st.metric` show things;
  `st.selectbox`, `st.slider`, `st.button`, `st.text_input` ask the user
  for something and return the answer.
- Charts from other libraries: `st.plotly_chart(fig)` (plotly) or
  `st.pyplot(fig)` (matplotlib).
- Libraries you can import: pandas, numpy, scikit-learn, sktime, plotly,
  matplotlib, polars. Others are not installed (ask the instructor).
- Every element: https://docs.streamlit.io, "API reference".

## If something goes wrong

| What you see | What to do |
|---|---|
| No **my app** in the sidebar | The file must be in `pages/` (next to `streamlit_app.py`, not inside another folder) and end in `.py`. Refresh the browser |
| Still no **my app**, and `pages` was missing and you created it | Streamlit only watches a `pages` folder that existed when it started. Ask the instructor to run `docker compose restart streamlit` on the gateway; refresh |
| `ModuleNotFoundError: No module named 'aiot_data'` | `pages` is in the wrong place: it must be in the same folder as `aiot_data.py` |
| `No sensor has sent data in the last hour` | Power a sensor node, wait a few seconds, refresh |
| The chart is empty | That field has no readings in the last hour; pick another or use `within="6h"` |
| The page did not change after editing | Did you save (Ctrl+S)? Is the file name in the sidebar the one you edited? |
| `IndentationError` | Lines inside `if` must start with 4 spaces; lines outside must not |
