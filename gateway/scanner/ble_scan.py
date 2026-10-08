"""Passive BLE advertisement scanner.

The only platform-facing module in the gateway. bleak selects its backend at
runtime: WinRT on Windows, BlueZ on Linux (Raspberry Pi, Uno Q), CoreBluetooth
on macOS. Nothing else in the codebase knows which radio is underneath.
"""

from __future__ import annotations

import asyncio
import sys
import time
from collections.abc import Callable

from ..core import COMPANY_ID, RawFrame, parse_manufacturer_data

try:
    from bleak import BleakScanner
    HAVE_BLEAK = True
except ImportError:
    HAVE_BLEAK = False

try:
    from bleak.args.bluez import OrPattern
except ImportError:
    try:
        from bleak.backends.bluezdbus.advertisement_monitor import OrPattern
    except ImportError:
        OrPattern = None  # Linux passive scanning unavailable; active scan is used


def _bluez_passive_args(company_id: int) -> dict:
    """BlueZ passive scanning (advertisement monitor) needs or_patterns.

    A BlueZ active scan filters duplicate reports, so a node that advertises
    every 100 ms is heard about once per ~10.5 s on the Uno Q and most `seq`
    values look lost. A passive monitor receives every advertisement. It needs
    bluetoothd --experimental (Experimental = true in /etc/bluetooth/main.conf).
    """
    if OrPattern is None or not sys.platform.startswith("linux"):
        return {}
    # AD type 0xFF = manufacturer specific data; first two bytes are the company ID
    pattern = OrPattern(0, 0xFF, company_id.to_bytes(2, "little"))
    return {"bluez": {"or_patterns": [pattern]}}


class BleSource:
    """Streams RawFrame objects from live BLE advertisements."""

    def __init__(self, company_id: int = COMPANY_ID, adapter: str | None = None,
                 kit_id: int | None = None):
        if not HAVE_BLEAK:
            raise RuntimeError(
                "bleak is not installed. Run: pip install bleak\n"
                "For development without a radio, use the simulator: python -m gateway simulate"
            )
        self.company_id = company_id
        self.adapter = adapter
        self.kit_id = kit_id

    async def run(self, on_frame: Callable[[RawFrame], None]) -> None:
        def detection(device, adv):
            data = adv.manufacturer_data.get(self.company_id)
            if data is None:
                return
            frame = parse_manufacturer_data(bytes(data), rx_time=time.time(),
                                            rssi=adv.rssi)
            if frame is None:
                return
            if self.kit_id is not None and frame.kit_id != self.kit_id:
                return
            on_frame(frame)

        kwargs = {"detection_callback": detection, "scanning_mode": "passive",
                  **_bluez_passive_args(self.company_id)}
        if self.adapter:
            kwargs["adapter"] = self.adapter  # BlueZ only; ignored elsewhere
        try:
            scanner = BleakScanner(**kwargs)
            async with scanner:
                print("[gateway] BLE scan mode: passive")
                while True:
                    await asyncio.sleep(3600)
        except Exception as exc:
            # WinRT and some BlueZ builds reject passive mode; active scan still
            # receives the same advertisement payloads. On BlueZ it also drops
            # repeats, so expect a low delivery ratio: say so instead of hiding it.
            print(f"[gateway] BLE scan mode: active (passive unavailable: "
                  f"{type(exc).__name__}: {exc})")
            kwargs.pop("scanning_mode", None)
            kwargs.pop("bluez", None)
            scanner = BleakScanner(**kwargs)
            async with scanner:
                while True:
                    await asyncio.sleep(3600)
