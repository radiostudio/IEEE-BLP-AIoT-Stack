"""Two devices under one sensor UID stay apart. Run:

    python -m gateway.tests.test_multi_device            SQLite
    python -m gateway.tests.test_multi_device influx     also against InfluxDB
                                                         (the configured server)
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

from ..agents.orchestrator import build_evidence_pack
from ..core import RawFrame
from ..decoder.registry import CardRegistry
from ..mcp_server.context import GatewayContext
from ..mcp_server.tools.deploy_rule import validate_rule_spec
from ..mcp_server.tools.list_sensors import list_sensors
from ..mcp_server.tools.query_timeseries import query_timeseries
from ..mcp_server.tools.read_latest import read_latest
from ..mcp_server.tools.validate_reading import validate_reading
from ..pipeline import Pipeline
from ..rules.engine import RuleEngine
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

    # tools without a mac answer per device, never mixed
    r = read_latest(ctx, "1:1")
    assert [(d["mac"], d["fields"]["temperature_c"]["value"]) for d in r["devices"]] \
        == [(MAC_A, 20.0), (MAC_B, 30.0)], r
    q = query_timeseries(ctx, "1:1", "temperature_c", now - 3600, now + 60)
    assert [(d["mac"], d["n"]) for d in q["devices"]] == [(MAC_A, 3), (MAC_B, 3)], q
    one = query_timeseries(ctx, "1:1", "temperature_c", now - 3600, now + 60, mac=MAC_B)
    assert one["mac"] == MAC_B and {p["value"] for p in one["points"]} == {30.0}, one
    v = validate_reading(ctx, "1:1", "temperature_c")
    assert [(d["mac"], d["verdict"]) for d in v["devices"]] == \
        [(MAC_A, "plausible"), (MAC_B, "plausible")], v
    assert validate_reading(ctx, "1:1", "temperature_c", mac=MAC_A)["mac"] == MAC_A

    # recipe evidence: one entry per device, plus a caveat naming both
    recipe = {"name": "t", "question": "q", "window_s": 3600,
              "sensors": [{"uid": "1:1", "field": "temperature_c", "role": "r"}]}
    pack = build_evidence_pack(ctx, recipe)
    assert sorted(pack["sensors"]) == [f"1:1@{MAC_A}.temperature_c",
                                       f"1:1@{MAC_B}.temperature_c"], pack["sensors"]
    assert any("has 2 devices" in c for c in pack["caveats"]), pack["caveats"]


def test_sqlite_two_devices():
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "t.db")
        try:
            _check_store(store)
        finally:
            store.close()


def test_one_device_keeps_the_plain_answer():
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "t.db")
        try:
            Pipeline(store, CardRegistry()).on_frame(_ds18b20(MAC_A, 1, 21.0, 0))
            ctx = GatewayContext(store=store, registry=CardRegistry())
            r = read_latest(ctx, "1:1")
            assert r["mac"] == MAC_A and "devices" not in r, r
            recipe = {"name": "t", "question": "q", "window_s": 3600,
                      "sensors": [{"uid": "1:1", "field": "temperature_c"}]}
            assert list(build_evidence_pack(ctx, recipe)["sensors"]) == \
                ["1:1.temperature_c"]
        finally:
            store.close()


def test_card_without_a_device():
    # a card exists (SHT40, type 17) but nothing has been received
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "t.db")
        try:
            ctx = GatewayContext(store=store, registry=CardRegistry())
            assert "error" in read_latest(ctx, "1:17")
            now = time.time()
            assert query_timeseries(ctx, "1:17", "temperature_c", now - 60, now)["n"] == 0
            assert validate_reading(ctx, "1:17", "temperature_c")["verdict"] == "unknown"
            # "what if it read ...?" works from the card alone
            assert validate_reading(ctx, "1:17", "temperature_c", 25.0)["verdict"] == "plausible"
            assert validate_reading(ctx, "1:17", "temperature_c", 500.0)["verdict"] == "implausible"
        finally:
            store.close()


def _engine(tmp: Path, *conds) -> RuleEngine:
    rules = tmp / "rules.d"
    rules.mkdir(exist_ok=True)
    for i, cond in enumerate(conds):
        (rules / f"r{i}.json").write_text(json.dumps({
            "name": f"r{i}", "when": {"all": [cond]}, "on_fault": "skip",
            "action": {"type": "log"}, "cooldown_s": 0}))
    return RuleEngine(Store(tmp / "t.db"), rules)


def test_rule_fires_on_healthy_device_beside_faulty_one():
    # both under 1:1; B reports sensor_ok off on every frame. Before the
    # per-device engine, each B frame reset the shared for_s timer.
    with tempfile.TemporaryDirectory() as tmp:
        eng = _engine(Path(tmp), {"sensor": "1:1", "field": "temperature_c",
                                  "op": ">", "value": 30, "for_s": 0.3})
        for _ in range(6):
            eng.evaluate("1:1", {"temperature_c": 35.0}, 1, mac=MAC_A)
            eng.evaluate("1:1", {"temperature_c": 0.0}, 0, mac=MAC_B)
            time.sleep(0.1)
        assert eng.fired_log, "rule never fired"
        eng.store.close()


def test_rule_restricted_to_one_mac():
    with tempfile.TemporaryDirectory() as tmp:
        eng = _engine(Path(tmp),
                      {"sensor": "1:1", "field": "temperature_c", "op": ">",
                       "value": 30, "mac": MAC_A.lower()},   # case does not matter
                      {"sensor": "1:1", "field": "temperature_c", "op": ">",
                       "value": 30, "mac": MAC_B})
        eng.evaluate("1:1", {"temperature_c": 20.0}, 1, mac=MAC_A)
        eng.evaluate("1:1", {"temperature_c": 35.0}, 1, mac=MAC_B)
        assert [f["rule"] for f in eng.fired_log] == ["r1"], eng.fired_log
        eng.store.close()


def test_deploy_rule_checks_the_mac():
    base = {"name": "x", "action": {"type": "log"}}
    cond = {"sensor": "1:1", "field": "temperature_c", "op": ">", "value": 30}
    assert not validate_rule_spec({**base, "when": {"all": [{**cond, "mac": MAC_A}]}})
    assert not validate_rule_spec({**base, "when": {"all": [cond]}})
    assert validate_rule_spec({**base, "when": {"all": [{**cond, "mac": "kitchen"}]}})


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
