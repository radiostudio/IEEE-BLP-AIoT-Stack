"""read_latest: most recent value per measurand for one sensor."""

from __future__ import annotations

import time

from ..context import GatewayContext


def read_latest(ctx: GatewayContext, sensor_uid: str, mac: str | None = None) -> dict:
    """mac selects one device; without it the newest reading under the uid wins."""
    latest = ctx.store.read_latest(sensor_uid, mac=mac)
    if not latest:
        return {"error": f"no readings stored for {sensor_uid}"
                         + (f" from {mac}" if mac else "")}
    now = time.time()
    return {
        "sensor_uid": sensor_uid,
        **({"mac": mac} if mac is not None else {}),
        "fields": {
            f: {
                "value": d["value"],
                "age_s": round(now - d["ts"], 1),
                "sensor_ok": bool(d["status"] & 0x01),
            }
            for f, d in latest.items()
        },
    }
