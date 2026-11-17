"""Read the gateway's sensor data from InfluxDB into pandas.

Shared by the notebooks and the Streamlit app in this folder. In the Docker
stack the address comes from INFLUX_URL / INFLUX_DB (set in compose.yaml);
outside Docker it defaults to an InfluxDB on this machine.

    import aiot_data
    aiot_data.sensors()                          # one row per device
    aiot_data.readings("1:1", "temperature_c")   # last hour, every device
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit

import pandas as pd
from influxdb import InfluxDBClient

INFLUX_URL = os.environ.get("INFLUX_URL", "http://localhost:8086")
INFLUX_DB = os.environ.get("INFLUX_DB", "aiot_blp")
MCP_URL = os.environ.get("MCP_URL", "http://localhost:8000/mcp")

# stored with every reading but not measurements
NOT_MEASURANDS = {"seq", "status", "rx_time"}


def client() -> InfluxDBClient:
    u = urlsplit(INFLUX_URL)
    return InfluxDBClient(host=u.hostname, port=u.port or 8086,
                          ssl=u.scheme == "https", database=INFLUX_DB)


def _q(text: str) -> str:
    """InfluxQL string literal."""
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _rows(query: str) -> list[dict]:
    return list(client().query(query).get_points())


def sensors(within: str = "1h") -> pd.DataFrame:
    """One row per device (sensor_uid + mac) that sent a reading within
    `within` (an InfluxDB duration: 15m, 1h, 7d ...), with its last values."""
    rows = []
    for s in client().query(
            f'SELECT LAST(*) FROM "raw"."readings" WHERE time > now() - {within} '
            f'GROUP BY "sensor_uid", "mac"').items():
        (_, tags), points = s
        for p in points:
            last = {k.removeprefix("last_"): v for k, v in p.items()
                    if k.startswith("last_") and v is not None
                    and k.removeprefix("last_") not in NOT_MEASURANDS}
            rows.append({"sensor_uid": tags["sensor_uid"], "mac": tags["mac"],
                         "fields": sorted(last), "last": last})
    df = pd.DataFrame(rows, columns=["sensor_uid", "mac", "fields", "last"])
    # 1:2 before 1:10
    key = df["sensor_uid"].map(lambda u: tuple(int(x) for x in u.split(":")))
    return df.assign(_k=key).sort_values(["_k", "mac"]).drop(columns="_k") \
             .reset_index(drop=True)


def readings(sensor_uid: str, field: str, mac: str | None = None,
             within: str = "1h") -> pd.DataFrame:
    """Raw readings of one field: columns time (UTC), mac, value, status.
    mac None = every device under the sensor_uid."""
    where = f'"sensor_uid" = {_q(sensor_uid)} AND time > now() - {within}'
    if mac:
        where += f' AND "mac" = {_q(mac)}'
    rows = _rows(f'SELECT "{field}" AS value, "status", "mac" '
                 f'FROM "raw"."readings" WHERE {where}')
    df = pd.DataFrame(rows, columns=["time", "value", "status", "mac"])
    df = df.dropna(subset=["value"])
    df["time"] = pd.to_datetime(df["time"], utc=True, format="ISO8601")
    return df[["time", "mac", "value", "status"]].reset_index(drop=True)
