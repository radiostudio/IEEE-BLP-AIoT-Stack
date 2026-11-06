"""Cloud-loop orchestrator.

Routes capstone questions to fusion recipes. A recipe names the sensors, the
alignment window, and the decision to output; the orchestrator gathers the
evidence through the same tool functions the MCP server exposes and builds an
evidence pack.

Two modes:
- offline (default): writes the evidence pack plus the recipe's reasoning
  prompt to data/evidence/; any LLM, including Claude via the MCP server, can
  take it from there.
- online: if the `anthropic` package and ANTHROPIC_API_KEY are available, the
  pack is sent to the model and the answer is stored alongside it.

Watchdog duty also lives here: check_liveness() flags sensors whose heartbeat
has gone quiet, which is the "Is Silence Good News?" pattern in code.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from ..core import PACKAGE_DIR
from ..mcp_server.context import GatewayContext
from ..mcp_server.tools.annotate import annotate, list_annotations
from ..mcp_server.tools.list_sensors import list_sensors
from ..mcp_server.tools.query_timeseries import query_timeseries
from ..mcp_server.tools.validate_reading import validate_reading

RECIPES_DIR = Path(__file__).resolve().parent / "recipes"
EVIDENCE_DIR = PACKAGE_DIR / "data" / "evidence"


def load_recipes() -> dict[str, dict]:
    recipes = {}
    for path in sorted(RECIPES_DIR.glob("*.json")):
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        recipes[doc["name"]] = doc
    return recipes


def build_evidence_pack(ctx: GatewayContext, recipe: dict,
                        window_s: float | None = None) -> dict:
    end = time.time()
    start = end - (window_s or recipe.get("window_s", 3600))
    # uid -> its devices; two nodes can share a uid and differ only by mac
    inventory: dict[str, list[dict]] = {}
    for s in list_sensors(ctx):
        inventory.setdefault(s["uid"], []).append(s)
    pack = {
        "question": recipe["question"],
        "recipe": recipe["name"],
        "window": {"start": start, "end": end},
        "sensors": {},
        "annotations": list_annotations(ctx, since=start),
        "caveats": [],
    }
    for spec in recipe["sensors"]:
        uid, field = spec["uid"], spec["field"]
        devices = inventory.get(uid, [])
        if not devices:
            pack["caveats"].append(f"{uid} ({spec.get('role')}) not present; "
                                   f"conclusions relying on it are weakened")
            continue
        if len(devices) > 1:
            pack["caveats"].append(
                f"{uid} has {len(devices)} devices "
                f"({', '.join(d['mac'] for d in devices)}); each is listed "
                f"separately, decide whether they measure the same place")
        for dev in devices:
            mac = dev["mac"]
            # one device keeps the plain "uid.field" key
            label = uid if len(devices) == 1 else f"{uid}@{mac}"
            series = query_timeseries(ctx, uid, field, start, end,
                                      agg=spec.get("agg", "mean"),
                                      bucket_s=spec.get("bucket_s", 60), mac=mac)
            verdict = validate_reading(ctx, uid, field, mac=mac)
            pack["sensors"][f"{label}.{field}"] = {
                "role": spec.get("role"),
                "mac": mac,
                "series": series,
                "latest_validation": {k: verdict[k] for k in
                                      ("verdict", "reasoning")},
                "delivery_ratio": dev["delivery_ratio"],
            }
            if verdict["verdict"] != "plausible":
                pack["caveats"].append(
                    f"{label}.{field} latest validation: {verdict['verdict']}")
    return pack


def run_recipe(ctx: GatewayContext, name: str,
               window_s: float | None = None) -> dict:
    recipes = load_recipes()
    if name not in recipes:
        return {"error": f"unknown recipe '{name}'",
                "available": sorted(recipes)}
    recipe = recipes[name]
    pack = build_evidence_pack(ctx, recipe, window_s)

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    out = EVIDENCE_DIR / f"{name}_{stamp}.json"
    out.write_text(json.dumps(pack, indent=2), encoding="utf-8")

    prompt = recipe.get("reasoning_prompt", "Reason over the evidence pack "
                        "and answer the question with a decision.")
    result = {"evidence_pack": str(out), "question": recipe["question"],
              "mode": "offline"}

    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            import anthropic
            client = anthropic.Anthropic()
            msg = client.messages.create(
                model=os.environ.get("GATEWAY_MODEL", "claude-sonnet-5"),
                max_tokens=2000,
                messages=[{"role": "user", "content":
                           f"{prompt}\n\nEvidence pack:\n{json.dumps(pack)[:150000]}"}],
            )
            answer = "".join(b.text for b in msg.content if b.type == "text")
            (out.with_suffix(".answer.md")).write_text(answer, encoding="utf-8")
            annotate(ctx, f"recipe '{name}' answered by model; see "
                     f"{out.with_suffix('.answer.md').name}", author="orchestrator")
            result.update({"mode": "online", "answer_file":
                           str(out.with_suffix(".answer.md"))})
        except Exception as exc:
            result["online_error"] = str(exc)
    return result


def check_liveness(ctx: GatewayContext, quiet_factor: float = 6.0) -> list[dict]:
    """Watchdog: a sensor is 'quiet' when nothing has arrived for more than
    quiet_factor times its sampling period. Quiet is reported, never assumed
    fine; alerts land in the deployment journal."""
    findings = []
    cards = {c.sensor_type_id: c for c in ctx.registry.all_cards()}
    now = time.time()
    for s in ctx.store.list_sensors():
        card = cards.get(s["sensor_type_id"])
        period = card.sampling_period_s if card else 10.0
        silent_for = now - s["last_seen"]
        if silent_for > period * quiet_factor:
            finding = {"uid": s["uid"], "mac": s["mac"], "part": s["part"],
                       "silent_for_s": round(silent_for, 1),
                       "expected_period_s": period}
            findings.append(finding)
            device = f"{s['uid']} {s['mac']}" if s["mac"] else s["uid"]
            annotate(ctx, f"liveness: {device} silent for "
                     f"{silent_for:.0f}s (expected every {period:.0f}s); "
                     f"dry-floor and dead-sensor are indistinguishable "
                     f"without this check", author="watchdog")
    return findings
