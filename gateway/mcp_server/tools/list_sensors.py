"""list_sensors: live inventory with last-seen and delivery ratio."""

from __future__ import annotations

import time

from ..context import GatewayContext


def list_sensors(ctx: GatewayContext) -> list[dict]:
    out = []
    now = time.time()
    for s in ctx.store.list_sensors():
        total = s["rx_count"] + s["lost_count"]
        out.append({
            "uid": s["uid"],
            "mac": s["mac"],     # one entry per device: a uid can have several
            "part": s["part"],
            "kit_id": s["kit_id"],
            "sensor_type_id": s["sensor_type_id"],
            "schema_version": s["schema_version"],
            "last_seen_s_ago": round(now - s["last_seen"], 1),
            "sensor_ok": bool(s["last_status"] & 0x01),
            "low_batt": bool(s["last_status"] & 0x02),
            "delivery_ratio": round(s["rx_count"] / total, 4) if total else 1.0,
        })
    return out
