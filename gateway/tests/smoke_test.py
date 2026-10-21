"""End-to-end self-test: simulator -> pipeline -> store -> tools -> rules.

No hardware, no network, no MCP transport: exercises the same code paths the
live gateway uses. Run with: python -m gateway smoke
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

from ..core import build_manufacturer_data, parse_manufacturer_data
from ..decoder.registry import CardRegistry
from ..mcp_server.context import GatewayContext
from ..mcp_server.tools.annotate import annotate
from ..mcp_server.tools.deploy_rule import (approve_rule, deploy_rule,
                                            ensure_capability_token)
from ..mcp_server.tools.describe_sensor import describe_sensor
from ..mcp_server.tools.list_sensors import list_sensors
from ..mcp_server.tools.query_timeseries import query_timeseries
from ..mcp_server.tools.read_latest import read_latest
from ..mcp_server.tools.validate_reading import validate_reading
from ..pipeline import Pipeline
from ..rules.engine import RuleEngine
from ..scanner.sim_source import SimulatedSource
from ..store.db import Store

PASS = "  ok:"


def main() -> int:
    failures = []

    def check(name: str, cond: bool, detail: str = ""):
        if cond:
            print(f"{PASS} {name}")
        else:
            failures.append(name)
            print(f"  FAIL: {name} {detail}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        store = Store(tmp / "smoke.db")
        registry = CardRegistry()
        expected_cards = len(list(registry.cards_dir.glob("*.json")))
        check(f"cards loaded ({expected_cards} expected)",
              len(registry.all_cards()) == expected_cards,
              f"got {len(registry.all_cards())}")

        # 1. frame codec round-trip
        src = SimulatedSource(kit_id=1)
        frames = []
        src.tick_once(frames.append)
        check("simulator emits all 14 types",
              len({f.sensor_type_id for f in frames}) == 14)
        f0 = frames[0]
        rt = parse_manufacturer_data(build_manufacturer_data(f0), f0.rx_time)
        check("payload codec round-trip",
              rt is not None and rt.seq == f0.seq and rt.payload == f0.payload)

        # 2. pipeline ingest, dedupe, rules
        rules_dir = tmp / "rules.d"
        rules_dir.mkdir()
        ctx = GatewayContext(store=store, registry=registry, rules_dir=rules_dir,
                             capability_token_file=tmp / ".capability_token")
        engine = RuleEngine(store, rules_dir)
        pipe = Pipeline(store, registry, engine)
        for _ in range(6):
            src.tick_once(pipe.on_frame)
            time.sleep(0.02)
        batch: list = []
        src.tick_once(batch.append)
        before_stored = pipe.frames_stored
        for f in batch:
            pipe.on_frame(f)
        for f in batch:
            pipe.on_frame(f)  # exact replay of frames the pipeline just saw
        check("dedupe drops replayed seq",
              pipe.frames_stored - before_stored == len(batch),
              f"stored {pipe.frames_stored - before_stored} of {len(batch)}")

        inventory = list_sensors(ctx)
        check("all sensors registered", len(inventory) == 14,
              f"got {len(inventory)}")
        check("delivery ratio tracked",
              all(0 < s["delivery_ratio"] <= 1 for s in inventory))

        # 3. tools over stored data
        latest = read_latest(ctx, "1:1")
        check("read_latest returns temperature",
              "temperature_c" in latest.get("fields", {}))
        card = describe_sensor(ctx, "1:6")
        check("describe_sensor serves the SCD41 card",
              card.get("part") == "SCD41")
        series = query_timeseries(ctx, "1:6", "co2_ppm",
                                  time.time() - 600, time.time())
        check("query_timeseries returns points", series["n"] >= 3,
              f"n={series['n']}")

        v = validate_reading(ctx, "1:1", "temperature_c")
        check("validate_reading: plausible in-band",
              v["verdict"] == "plausible", str(v))
        v = validate_reading(ctx, "1:1", "temperature_c", value=1000.0)
        check("validate_reading: 1000 degC rejected",
              v["verdict"] == "implausible", str(v))

        ann = annotate(ctx, "smoke test ran", author="smoke")
        check("annotate writes the journal", "annotation_id" in ann)

        # 4. deploy_rule governance
        spec = {"name": "smoke_rule",
                "when": {"all": [{"sensor": "1:1", "field": "temperature_c",
                                  "op": ">", "value": -100}]},
                "action": {"type": "log", "message": "smoke rule fired"},
                "cooldown_s": 60}
        bad = deploy_rule(ctx, spec, "wrong-token")
        check("deploy_rule rejects a bad token", bad["status"] == "rejected")
        good = deploy_rule(ctx, spec, ensure_capability_token(ctx))
        check("deploy_rule lands as pending",
              good["status"] == "pending_approval")
        engine.reload()
        check("pending rule does not run",
              all(r.get("name") != "smoke_rule" for r in engine.rules))
        approve_rule(ctx, "smoke_rule")
        engine.reload()
        check("approved rule loads",
              any(r.get("name") == "smoke_rule" for r in engine.rules))
        src.tick_once(pipe.on_frame)
        check("approved rule fires on data",
              any(r["rule"] == "smoke_rule" for r in engine.fired_log))

        # 5. fault injection visible end to end
        src.inject_fault(1, "stuck")
        for _ in range(3):
            src.tick_once(pipe.on_frame)
        pts = query_timeseries(ctx, "1:1", "temperature_c",
                               time.time() - 600, time.time())["points"]
        stuck_tail = {round(p["value"], 2) for p in pts[-3:]}
        check("stuck fault produces frozen values", len(stuck_tail) == 1,
              str(stuck_tail))

        store.close()

    print()
    if failures:
        print(f"SMOKE TEST FAILED: {len(failures)} failure(s): {failures}")
        return 1
    print("SMOKE TEST PASSED: scanner->decode->store->tools->rules all healthy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
