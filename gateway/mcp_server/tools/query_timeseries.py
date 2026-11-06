"""query_timeseries: raw or aggregated series over a window."""

from __future__ import annotations

from ..context import GatewayContext
from .devices import pick_devices


def _one(ctx: GatewayContext, sensor_uid: str, field: str, start: float,
         end: float, agg: str | None, bucket_s: int, mac: str | None) -> dict:
    points = ctx.store.query_timeseries(sensor_uid, field, start, end, agg,
                                        bucket_s, mac=mac)
    return {
        "sensor_uid": sensor_uid,
        **({"mac": mac} if mac is not None else {}),
        "field": field,
        "start": start,
        "end": end,
        "agg": agg,
        "bucket_s": bucket_s if agg else None,
        "n": len(points),
        "points": points,
    }


def query_timeseries(ctx: GatewayContext, sensor_uid: str, field: str,
                     start: float, end: float,
                     agg: str | None = None, bucket_s: int = 60,
                     mac: str | None = None) -> dict:
    """mac selects one device. Without it: the uid's only device, or one
    series per device under "devices" when the uid has several."""
    macs = pick_devices(ctx, sensor_uid, mac)
    if len(macs) == 1:
        return _one(ctx, sensor_uid, field, start, end, agg, bucket_s, macs[0])
    return {"sensor_uid": sensor_uid, "field": field,
            "devices": [_one(ctx, sensor_uid, field, start, end, agg, bucket_s, m)
                        for m in macs]}
