"""Devices under one sensor uid.

Two nodes of one type with the same kit ID share a uid ("1:2") and differ
only by their Bluetooth MAC. Tools take an optional mac; without one they
answer per device when the uid has several, so readings are never mixed.
"""

from __future__ import annotations

from ..context import GatewayContext


def devices_of(ctx: GatewayContext, sensor_uid: str) -> list[str]:
    """MACs seen under the uid, sorted; empty when the uid was never seen."""
    return sorted(s["mac"] for s in ctx.store.list_sensors()
                  if s["uid"] == sensor_uid)


def pick_devices(ctx: GatewayContext, sensor_uid: str,
                 mac: str | None) -> list[str | None]:
    """What a tool should answer for: the given mac; else the uid's single
    device; else every device (several); else [None] (none seen: the store
    is asked without a mac filter and returns whatever it has, usually nothing)."""
    if mac is not None:
        return [mac]
    macs = devices_of(ctx, sensor_uid)
    return macs if macs else [None]
