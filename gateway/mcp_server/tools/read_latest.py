"""read_latest: most recent value per measurand for one sensor."""

from __future__ import annotations

import time

from ..context import GatewayContext
from .devices import pick_devices


def _one(ctx: GatewayContext, sensor_uid: str, mac: str | None) -> dict:
    latest = ctx.store.read_latest(sensor_uid, mac=mac)
    head = {"sensor_uid": sensor_uid, **({"mac": mac} if mac is not None else {})}
    if not latest:
        return {**head, "error": f"no readings stored for {sensor_uid}"
                                 + (f" from {mac}" if mac else "")}
    now = time.time()
    return {
        **head,
        "fields": {
            f: {
                "value": d["value"],
                "age_s": round(now - d["ts"], 1),
                "sensor_ok": bool(d["status"] & 0x01),
            }
            for f, d in latest.items()
        },
    }


def read_latest(ctx: GatewayContext, sensor_uid: str, mac: str | None = None) -> dict:
    """mac selects one device. Without it: the uid's only device, or one
    answer per device under "devices" when the uid has several."""
    macs = pick_devices(ctx, sensor_uid, mac)
    if len(macs) == 1:
        return _one(ctx, sensor_uid, macs[0])
    return {"sensor_uid": sensor_uid,
            "devices": [_one(ctx, sensor_uid, m) for m in macs]}
