"""Read the gateway's sensor data from InfluxDB into pandas.

The notebook and the Streamlit apps in this folder use this file, so you do
not have to write database code yourself. Use it like this:

    import aiot_data
    devices = aiot_data.sensors()                       # one row per device
    df = aiot_data.readings("1:1", "temperature_c")     # last hour of one field

Words used below:

- InfluxDB: the database where the gateway stores every sensor reading. It is
  a "time-series" database: each reading has a time, some labels (called
  "tags") and some numbers (called "fields").
- sensor_uid: the sensor ID, "kit:type", e.g. "1:1" is kit 1, sensor type 1
  (DS18B20 temperature). A tag.
- mac: the Device ID, the Bluetooth address of the sensor node, e.g.
  "44:1D:64:C1:34:32". Two nodes can have the same sensor_uid; the mac tells
  them apart. A tag.
- field: one measured quantity, e.g. "temperature_c" or "co2_ppm".
- pandas DataFrame: a table in Python, with named columns and numbered rows.

Where the database is: in the Docker stack, INFLUX_URL and INFLUX_DB are set
in compose.yaml. Outside Docker, an InfluxDB on this machine is used.
"""

# --- Libraries ---------------------------------------------------------------
import os                                   # to read settings (environment variables)
from urllib.parse import urlsplit           # to split "http://influxdb:8086" into parts

import pandas as pd                         # tables (DataFrames)
from influxdb import InfluxDBClient         # talks to InfluxDB version 1
from influxdb.exceptions import InfluxDBClientError   # the error InfluxDB reports

# --- Settings ----------------------------------------------------------------
# os.environ.get(name, default) reads an environment variable. Docker sets
# these for us; the second value is used when the variable is not set.
INFLUX_URL = os.environ.get("INFLUX_URL", "http://localhost:8086")
INFLUX_DB = os.environ.get("INFLUX_DB", "aiot_blp")
MCP_URL = os.environ.get("MCP_URL", "http://localhost:8000/mcp")

# The time zone for the times in our tables. InfluxDB stores every time in
# UTC (the world's reference time); we convert it to local time, so that a
# reading taken at 10:30 in India shows as 10:30, not 05:00.
# "Asia/Kolkata" is the name for Indian Standard Time (IST, UTC + 5:30).
# Docker sets TZ in compose.yaml (changeable in .env).
TIMEZONE = os.environ.get("TZ", "Asia/Kolkata")

# The gateway stores these numbers with every reading, but they are not
# measurements (a counter, a status code and the arrival time), so we skip them.
NOT_MEASURANDS = ["seq", "status", "rx_time"]


def client():
    """Open a connection to InfluxDB and return it."""
    # Split the address into its parts:
    #   "http://influxdb:8086" -> scheme "http", hostname "influxdb", port 8086
    url = urlsplit(INFLUX_URL)

    # If the address has no port number, use InfluxDB's usual port, 8086.
    port = url.port
    if port is None:
        port = 8086

    # "https" means an encrypted connection; ours is normally plain "http".
    use_https = False
    if url.scheme == "https":
        use_https = True

    connection = InfluxDBClient(host=url.hostname, port=port, ssl=use_https,
                                database=INFLUX_DB)
    return connection


def quote(text):
    """Put text in single quotes for an InfluxDB query: 1:1 -> '1:1'.

    In an InfluxDB query, text values must be in single quotes. A quote or
    backslash inside the text gets a backslash in front, so it cannot end the
    text early and break the query.
    """
    text = text.replace("\\", "\\\\")       # \  becomes  \\
    text = text.replace("'", "\\'")         # '  becomes  \'
    return "'" + text + "'"


def run_query(query):
    """Send a query to InfluxDB and return the result.

    Returns None when the database does not exist yet. That happens on a new
    installation before the gateway's first start (the gateway creates it).
    Any other problem, e.g. InfluxDB not running, is raised as an error.
    """
    try:
        result = client().query(query)
        return result
    except InfluxDBClientError as error:
        # InfluxDB says "database not found" or "retention policy not found"
        if "not found" in str(error):
            return None
        # a different error: let it through, so the caller can show it
        raise


def device_order(row):
    """Sort devices by sensor ID, then Device ID.

    "1:2" must come before "1:10". Compared as text, "1:10" would come first
    (because the character "1" is smaller than "2"), so we compare the
    numbers instead: (1, 2) before (1, 10).
    """
    kit, sensor_type = row["sensor_uid"].split(":")     # "1:10" -> "1", "10"
    return (int(kit), int(sensor_type), row["mac"])


def sensors(within="1h"):
    """A table with one row per device that sent a reading in the last `within`.

    within: how far back to look, as an InfluxDB duration: "15m" (minutes),
            "1h" (hours), "24h", "7d" (days).

    The table has these columns:
      sensor_uid  the sensor ID, e.g. "1:1"
      mac         the Device ID (Bluetooth address)
      fields      a list of the field names this device reports
      last        the latest value of each field, e.g. {"temperature_c": 26.5}
    """
    # The query, in InfluxQL (InfluxDB's SQL-like language):
    #   SELECT LAST(*)        the latest value of every field
    #   FROM "raw"."readings" the table of raw readings ("raw" = keep 7 days)
    #   WHERE time > now() - 1h   only the last hour
    #   GROUP BY sensor_uid, mac  one answer per device
    query = (
        'SELECT LAST(*) FROM "raw"."readings" '
        f'WHERE time > now() - {within} '
        'GROUP BY "sensor_uid", "mac"'
    )
    result = run_query(query)

    rows = []                     # we collect one dictionary per device here
    if result is not None:
        # result.items() gives one group per device. Each group is
        # ((measurement name, tags), points); the tags hold sensor_uid and mac.
        for (measurement, tags), points in result.items():
            for point in points:
                # point is a dictionary, e.g.
                #   {"time": ..., "last_temperature_c": 26.5, "last_seq": 41, ...}
                last = {}
                for column, value in point.items():
                    # LAST(*) names its columns "last_<field>"; skip "time"
                    if not column.startswith("last_"):
                        continue
                    # "last_temperature_c" -> "temperature_c"
                    field = column.removeprefix("last_")
                    # skip the counter, status and arrival time
                    if field in NOT_MEASURANDS:
                        continue
                    # None means this device does not report this field
                    # (each sensor type has different fields)
                    if value is None:
                        continue
                    last[field] = value

                row = {
                    "sensor_uid": tags["sensor_uid"],
                    "mac": tags["mac"],
                    "fields": sorted(last),       # the field names, A to Z
                    "last": last,
                }
                rows.append(row)

    # sort the devices: 1:1, 1:2, ... 1:10, and by Device ID inside a sensor
    rows.sort(key=device_order)

    # turn the list of dictionaries into a pandas table
    table = pd.DataFrame(rows, columns=["sensor_uid", "mac", "fields", "last"])
    return table


def readings(sensor_uid, field, mac=None, within="1h"):
    """A table with the readings of one field of one sensor.

    sensor_uid: the sensor ID, e.g. "1:1"
    field:      the field name, e.g. "temperature_c"
    mac:        one Device ID, or None (the default) for every device of
                the sensor
    within:     how far back to look: "15m", "1h", "24h", "7d", ...

    The table has these columns:
      time    when the reading was taken, in local time (TIMEZONE, e.g. IST)
      mac     which device sent it
      value   the measured number
      status  status bits from the sensor; bit 0 = 1 means "sensor ok"
    """
    # Build the WHERE part of the query step by step.
    # First: this sensor, and only the chosen time window.
    where = f'"sensor_uid" = {quote(sensor_uid)} AND time > now() - {within}'

    # Then, if a Device ID was given: only that device.
    if mac is not None:
        where = where + f' AND "mac" = {quote(mac)}'

    # SELECT "temperature_c" AS value  ->  the column is called "value",
    # whatever the field is, so the rest of the code works for every field.
    query = f'SELECT "{field}" AS value, "status", "mac" FROM "raw"."readings" WHERE {where}'
    result = run_query(query)

    # get_points() gives one dictionary per reading:
    #   {"time": "2026-11-17T10:54:07Z", "value": 26.5, "status": 1, "mac": "..."}
    rows = []
    if result is not None:
        rows = list(result.get_points())

    # turn the list into a pandas table
    df = pd.DataFrame(rows, columns=["time", "value", "status", "mac"])

    # A reading from this sensor that does not contain this field has an
    # empty value (NaN, "not a number"); remove those rows.
    df = df.dropna(subset=["value"])

    # The time arrives as text ("2026-11-17T10:54:07Z"); convert it to a real
    # date and time, so pandas can plot it and do time calculations.
    # The "Z" at the end means UTC, so we read it as UTC first ...
    df["time"] = pd.to_datetime(df["time"], utc=True, format="ISO8601")

    # ... then convert it to local time. tz_convert changes how the time is
    # shown, not the moment itself: 05:00 UTC becomes 10:30 IST.
    df["time"] = df["time"].dt.tz_convert(TIMEZONE)

    # put the columns in a clear order
    df = df[["time", "mac", "value", "status"]]

    # number the rows 0, 1, 2, ... again (dropna left gaps in the numbers)
    df = df.reset_index(drop=True)
    return df
