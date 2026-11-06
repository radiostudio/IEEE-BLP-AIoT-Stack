"""deploy_rule: agent-authored edge rules, behind a capability token and a
human approval step.

The tool validates the rule spec and writes `<name>.json.pending`. Nothing
runs until a human executes `python -m gateway approve-rule <name>`. An LLM
can therefore design control logic but can never place itself, or its
mistakes, directly into the control path.
"""

from __future__ import annotations

import json
import re
import secrets

from ..context import GatewayContext

_ALLOWED_ACTIONS = {"log", "annotate", "webhook", "gpio"}
_ALLOWED_OPS = {"<", "<=", ">", ">=", "==", "!="}
# a Bluetooth MAC (AA:BB:CC:DD:EE:FF), or the UUID macOS reports instead
_DEVICE_ID = re.compile(r"^(?:[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}"
                        r"|[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12})$")


def ensure_capability_token(ctx: GatewayContext) -> str:
    """Create the token on first use; the human shares it with the agent."""
    f = ctx.capability_token_file
    if not f.exists():
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(secrets.token_hex(16), encoding="utf-8")
    return f.read_text(encoding="utf-8").strip()


def validate_rule_spec(spec: dict) -> list[str]:
    errors = []
    if not spec.get("name", "").replace("_", "").replace("-", "").isalnum():
        errors.append("name must be alphanumeric with _ or -")
    conds = spec.get("when", {}).get("all")
    if not isinstance(conds, list) or not conds:
        errors.append("when.all must be a non-empty list of conditions")
    else:
        for i, c in enumerate(conds):
            for key in ("sensor", "field", "op", "value"):
                if key not in c:
                    errors.append(f"condition {i}: missing '{key}'")
            if c.get("op") not in _ALLOWED_OPS:
                errors.append(f"condition {i}: op must be one of {sorted(_ALLOWED_OPS)}")
            if "mac" in c and not (isinstance(c["mac"], str)
                                   and _DEVICE_ID.match(c["mac"])):
                errors.append(f"condition {i}: mac must look like "
                              f"AA:BB:CC:DD:EE:FF (see list_sensors)")
    action = spec.get("action", {})
    if action.get("type") not in _ALLOWED_ACTIONS:
        errors.append(f"action.type must be one of {sorted(_ALLOWED_ACTIONS)}")
    return errors


def deploy_rule(ctx: GatewayContext, spec: dict, capability_token: str) -> dict:
    expected = ensure_capability_token(ctx)
    if capability_token != expected:
        return {"status": "rejected",
                "reason": "invalid capability token; ask the gateway owner for it"}
    errors = validate_rule_spec(spec)
    if errors:
        return {"status": "rejected", "reason": "spec validation failed",
                "errors": errors}
    ctx.rules_dir.mkdir(parents=True, exist_ok=True)
    pending = ctx.rules_dir / f"{spec['name']}.json.pending"
    pending.write_text(json.dumps(spec, indent=2), encoding="utf-8")
    ctx.store.annotate(f"rule '{spec['name']}' deployed as pending; awaiting "
                       f"human approval", author="deploy_rule")
    return {
        "status": "pending_approval",
        "file": str(pending),
        "approve_with": f"python -m gateway approve-rule {spec['name']}",
        "note": "the rule will not run until a human approves it",
    }


def approve_rule(ctx: GatewayContext, name: str) -> dict:
    pending = ctx.rules_dir / f"{name}.json.pending"
    if not pending.exists():
        return {"status": "error", "reason": f"no pending rule named '{name}'"}
    target = ctx.rules_dir / f"{name}.json"
    pending.rename(target)
    ctx.store.annotate(f"rule '{name}' approved and activated", author="human")
    return {"status": "approved", "file": str(target)}
