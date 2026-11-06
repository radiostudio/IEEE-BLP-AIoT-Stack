"""Two devices under one sensor UID stay apart. Run:

    python -m gateway.tests.test_multi_device            SQLite
    python -m gateway.tests.test_multi_device influx     also against InfluxDB
                                                         (the configured server)
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import time
from pathlib import Path

from ..core import RawFrame
from ..decoder.registry import CardRegistry
from ..mcp_server.context import GatewayContext
from ..mcp_server.tools.list_sensors import list_sensors
from ..mcp_server.tools.read_latest import read_latest
from ..pipeline import Pipeline
from ..scanner.sim_source import SimulatedSource, sim_mac
from ..store.db import OldDatabaseFormat, Store
from .smoke_test import _open_store

MAC_A, MAC_B = sim_mac(1, 1, 1), sim_mac(1, 1, 2)


def _ds18b20(mac: str, seq: int, temp_c: float, tick_s: float) -> RawFrame:
    payload = int(temp_c * 100).to_bytes(2, "little", signed=True)
    return RawFrame(kit_id=1, sensor_type_id=1, schema_version=1, seq=seq,
                    tick_ms=int(tick_s * 1000), status=1, payload=payload,
                    mac=mac)


def _check_store(store) -> None:
    pipe = Pipeline(store, CardRegistry())
    # same kit ID, type and seq numbers: before the mac, B's frames were
    # dropped as duplicates of A's and the two shared one inventory row
    for i, seq in enumerate((10, 11, 12)):
        pipe.on_frame(_ds18b20(MAC_A, seq, 20.0, i))
        pipe.on_frame(_ds18b20(MAC_B, seq, 30.0, i))
    assert pipe.frames_stored == 6, f"stored {pipe.frames_stored} of 6"

    ctx = GatewayContext(store=store, registry=CardRegistry())
    devices = [(s["uid"], s["mac"]) for s in list_sensors(ctx)]
    assert devices == [("1:1", MAC_A), ("1:1", MAC_B)], devices
    for s in list_sensors(ctx):
        assert s["delivery_ratio"] == 1.0, s   # no false losses from shared seq

    a = read_latest(ctx, "1:1", mac=MAC_A)["fields"]["temperature_c"]["value"]
    b = read_latest(ctx, "1:1", mac=MAC_B)["fields"]["temperature_c"]["value"]
    assert (a, b) == (20.0, 30.0), (a, b)

    now = time.time()
    for mac, want in ((MAC_A, 20.0), (MAC_B, 30.0)):
        pts = store.query_timeseries("1:1", "temperature_c", now - 3600, now + 60,
                                     mac=mac)
        assert [p["value"] for p in pts] == [want] * 3, (mac, pts)
        band = store.query_timeseries("1:1", "temperature_c", now - 3600, now + 60,
                                      agg="band", bucket_s=3600, mac=mac)
        assert all(p["min"] == p["max"] == want for p in band), (mac, band)
    both = store.query_timeseries("1:1", "temperature_c", now - 3600, now + 60)
    assert len(both) == 6, both   # no mac: every device under the uid


def test_sqlite_two_devices():
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "t.db")
        try:
            _check_store(store)
        finally:
            store.close()


def test_simulator_twin():
    src = SimulatedSource(kit_id=1, types=[1], twins=[1])
    frames: list = []
    src.tick_once(frames.append)
    assert sorted(f.mac for f in frames) == [MAC_A, MAC_B], [f.mac for f in frames]
    assert {f.uid for f in frames} == {"1:1"}


def test_old_database_is_refused():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "old.db"
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE sensors (uid TEXT PRIMARY KEY, kit_id INTEGER)")
        conn.close()
        try:
            Store(path)
        except OldDatabaseFormat:
            return
        raise AssertionError("old-format database was opened")


def influx_two_devices():
    with tempfile.TemporaryDirectory() as tmp:
        store = _open_store("influx", Path(tmp))
        try:
            _check_store(store)
        finally:
            store.query(f"DROP DATABASE \"{store.database}\"", write=True)
            store.close()


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"  ok: {name}")
    if "influx" in sys.argv[1:]:
        influx_two_devices()
        print("  ok: influx_two_devices")
