"""Gateway CLI.

  python -m gateway run          live BLE scan -> store (+rules, +dashboard)
  python -m gateway simulate     same pipeline fed by the 14-sensor simulator
  python -m gateway mcp          MCP server over stdio (for Claude)
  python -m gateway dashboard    dashboard only, against the existing database
  python -m gateway approve-rule <name>   activate a pending agent-authored rule
  python -m gateway token        print the deploy_rule capability token
  python -m gateway recipe <name>         run a fusion recipe (cloud loop)
  python -m gateway liveness     watchdog pass: flag silent sensors
  python -m gateway downsample   roll old raw rows into aggregates
  python -m gateway smoke        end-to-end self-test, no hardware needed

Run from the directory that contains the gateway/ package.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from .core import load_config
from .mcp_server.context import GatewayContext
from .pipeline import Pipeline
from .rules.engine import RuleEngine


def _ctx() -> GatewayContext:
    return GatewayContext.from_config(load_config())


async def _run_with_status(src, pipe: Pipeline, interval_s: int = 10) -> None:
    async def status():
        last = 0
        while True:
            await asyncio.sleep(interval_s)
            print(f"[gateway] {pipe.frames_in} frames received "
                  f"(+{pipe.frames_in - last} in the last {interval_s}s), "
                  f"{pipe.frames_stored} stored; latest values on the dashboard")
            last = pipe.frames_in
    task = asyncio.get_running_loop().create_task(status())
    try:
        await src.run(pipe.on_frame)
    finally:
        task.cancel()


def cmd_run(args) -> None:
    from .dashboard.server import serve
    from .scanner.ble_scan import BleSource
    cfg = load_config()
    ctx = _ctx()
    engine = RuleEngine(ctx.store)
    pipe = Pipeline(ctx.store, ctx.registry, engine)
    if not args.no_dashboard:
        serve(ctx, port=args.port or cfg.get("dashboard_port", 8080),
              background=True)
    src = BleSource(company_id=cfg.get("company_id", 0xFFFF),
                    adapter=cfg.get("ble_adapter"), kit_id=cfg.get("kit_id"))
    print("[gateway] scanning BLE advertisements (Ctrl+C to stop)")
    try:
        asyncio.run(_run_with_status(src, pipe))
    except KeyboardInterrupt:
        print(f"\n[gateway] stopped. frames received: {pipe.frames_in}, "
              f"stored: {pipe.frames_stored}")


def cmd_simulate(args) -> None:
    from .dashboard.server import serve
    from .scanner.sim_source import SimulatedSource
    cfg = load_config()
    ctx = _ctx()
    engine = RuleEngine(ctx.store)
    pipe = Pipeline(ctx.store, ctx.registry, engine)
    if not args.no_dashboard:
        serve(ctx, port=args.port or cfg.get("dashboard_port", 8080),
              background=True)
    src = SimulatedSource(kit_id=1, speedup=args.speedup)
    if args.fault:
        type_id, fault = args.fault.split(":")
        src.inject_fault(int(type_id), fault)
        print(f"[sim] fault injected on type {type_id}: {fault}")
    print("[gateway] simulating all 14 SIMs (Ctrl+C to stop)")
    print("[gateway] open the dashboard in your browser to watch the values")
    try:
        asyncio.run(_run_with_status(src, pipe))
    except KeyboardInterrupt:
        print(f"\n[gateway] stopped. frames received: {pipe.frames_in}, "
              f"stored: {pipe.frames_stored}")


def cmd_mcp(args) -> None:
    from .mcp_server.server import build_server
    build_server(_ctx()).run(transport="streamable-http")


def cmd_dashboard(args) -> None:
    from .dashboard.server import serve
    cfg = load_config()
    serve(_ctx(), port=args.port or cfg.get("dashboard_port", 8080))


def cmd_approve_rule(args) -> None:
    from .mcp_server.tools.deploy_rule import approve_rule
    print(json.dumps(approve_rule(_ctx(), args.name), indent=2))


def cmd_token(args) -> None:
    from .mcp_server.tools.deploy_rule import ensure_capability_token
    print(ensure_capability_token(_ctx()))


def cmd_recipe(args) -> None:
    from .agents.orchestrator import run_recipe
    print(json.dumps(run_recipe(_ctx(), args.name, args.window), indent=2))


def cmd_liveness(args) -> None:
    from .agents.orchestrator import check_liveness
    findings = check_liveness(_ctx())
    print(json.dumps(findings, indent=2) if findings
          else "all sensors alive within expected periods")


def cmd_downsample(args) -> None:
    from .store.downsample import downsample
    cfg = load_config()
    ctx = _ctx()
    print(json.dumps(downsample(ctx.store,
                                period_s=cfg.get("downsample_period_s", 300),
                                keep_raw_s=args.keep_raw_s), indent=2))


def cmd_smoke(args) -> None:
    from .tests.smoke_test import main as smoke_main
    sys.exit(smoke_main())


def cmd_tool(args) -> None:
    # CLI access to the same tool functions the MCP server exposes, so the
    # edge-first workshop works with zero LLM: students call the tools by
    # hand and play the agent's role themselves.
    import time
    from .mcp_server.tools.annotate import annotate, list_annotations
    from .mcp_server.tools.describe_sensor import describe_sensor
    from .mcp_server.tools.list_sensors import list_sensors
    from .mcp_server.tools.query_timeseries import query_timeseries
    from .mcp_server.tools.read_latest import read_latest
    from .mcp_server.tools.validate_reading import validate_reading
    ctx = _ctx()
    name, a = args.name, args.args
    if name == "list_sensors":
        out = list_sensors(ctx)
    elif name == "describe_sensor":
        out = describe_sensor(ctx, a[0])
    elif name == "read_latest":
        out = read_latest(ctx, a[0])
    elif name == "validate_reading":
        # optional third arg: a hypothetical value to test ("what if it read 1000?")
        value = float(a[2]) if len(a) > 2 else None
        out = validate_reading(ctx, a[0], a[1], value)
    elif name == "query_timeseries":
        # args: uid field minutes [agg]; minutes-ago windowing beats epoch
        # seconds for humans at a terminal
        minutes = float(a[2]) if len(a) > 2 else 60
        agg = a[3] if len(a) > 3 else None
        out = query_timeseries(ctx, a[0], a[1],
                               time.time() - minutes * 60, time.time(), agg)
    elif name == "annotate":
        out = annotate(ctx, a[0], a[1] if len(a) > 1 else None, author="student")
    elif name == "list_annotations":
        out = list_annotations(ctx)
    else:
        out = {"error": f"unknown tool '{name}'",
               "tools": ["list_sensors", "describe_sensor", "read_latest",
                          "validate_reading", "query_timeseries", "annotate",
                          "list_annotations"]}
    print(json.dumps(out, indent=2))


def main() -> None:
    p = argparse.ArgumentParser(prog="gateway", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("run"); s.add_argument("--no-dashboard", action="store_true")
    s.add_argument("--port", type=int, default=None)
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("simulate")
    s.add_argument("--no-dashboard", action="store_true")
    s.add_argument("--port", type=int, default=None)
    s.add_argument("--speedup", type=float, default=1.0)
    s.add_argument("--fault", help="type_id:fault e.g. 1:stuck, 7:offset, 13:dead")
    s.set_defaults(fn=cmd_simulate)

    sub.add_parser("mcp").set_defaults(fn=cmd_mcp)
    s = sub.add_parser("dashboard")
    s.add_argument("--port", type=int, default=None)
    s.set_defaults(fn=cmd_dashboard)

    s = sub.add_parser("approve-rule"); s.add_argument("name")
    s.set_defaults(fn=cmd_approve_rule)

    sub.add_parser("token").set_defaults(fn=cmd_token)

    s = sub.add_parser("recipe"); s.add_argument("name")
    s.add_argument("--window", type=float, default=None)
    s.set_defaults(fn=cmd_recipe)

    sub.add_parser("liveness").set_defaults(fn=cmd_liveness)

    s = sub.add_parser("downsample")
    s.add_argument("--keep-raw-s", type=int, default=7 * 86400)
    s.set_defaults(fn=cmd_downsample)

    sub.add_parser("smoke").set_defaults(fn=cmd_smoke)

    s = sub.add_parser("tool", help="call a gateway tool from the CLI (no LLM needed)")
    s.add_argument("name")
    s.add_argument("args", nargs="*")   # tool-specific positional arguments, documented in the workshop workflow doc
    s.set_defaults(fn=cmd_tool)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
