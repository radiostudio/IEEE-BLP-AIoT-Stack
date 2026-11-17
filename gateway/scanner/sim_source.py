"""Simulated SIM fleet for development without hardware.

Generates BLE-identical frames for all 14 sensor types, including sequence
counters, monotonic ticks, status bits, and instructor-style fault injection.
This is not listed in the architecture document's tree; it exists so the
gateway can be built and tested on a laptop, and it doubles as the reference
implementation of the payload spec for SIM firmware authors.
"""

from __future__ import annotations

import asyncio
import math
import random
import struct
import time
from collections.abc import Callable

from ..core import (STATUS_FAULT_INJECTED, STATUS_SENSOR_OK, RawFrame)


# Timed faults (stuck, offset, spike, drift): FAULT_DELAY_S of normal
# readings first, so the data shows before -> during -> after, then the
# fault for its duration (simulate --duration, default FAULT_DURATION_S),
# then normal readings again. Times are real seconds, independent of
# --speedup. "dead" starts at once and never ends.
FAULT_DELAY_S = 30.0      # normal readings before the fault starts
FAULT_DURATION_S = 60.0   # default fault length
# spike and drift change the first 16-bit value of the payload in raw units,
# the way the SIM firmware's generic offset does, so they work for every
# analog sensor without per-sensor code (not meaningful for 0/1 sensors).
SPIKE_EVERY_S = 10.0      # spike: one spiked reading every 10 s (5 in 50 s)
SPIKE_RAW = 0x2000        # by +8192 raw units: +81.92 degC on a DS18B20, out of any band
DRIFT_STEP_S = 5.0        # drift: one step every 5 s ...
DRIFT_STEP_RAW = 50       # ... of 50 raw units: +0.5 degC on a DS18B20 (+6 degC/min,
                          # under its 10 degC/min card limit), +30 degC in 5 minutes
# offset: per-sensor in the generators below; DS18B20 +3 degC (6x its accuracy,
# still a believable temperature: only a neighbouring sensor reveals it)


def _bump_first(payload: bytes, delta: int) -> bytes:
    """payload with delta added to its first 16-bit little-endian value."""
    if len(payload) < 2:
        return payload
    v = (payload[0] | payload[1] << 8) + delta
    return bytes([v & 0xFF, (v >> 8) & 0xFF]) + payload[2:]


def _diurnal(base: float, swing: float, phase: float = 0.0) -> float:
    day = (time.time() % 86400) / 86400
    return base + swing * math.sin(2 * math.pi * (day + phase))


class _Sim:
    def __init__(self, type_id: int, period_s: float, gen: Callable[["_Sim"], bytes],
                 mac: str = ""):
        self.type_id = type_id
        self.mac = mac
        self.period_s = period_s
        self.gen = gen
        self.seq = random.randint(0, 1000)
        self.boot = time.monotonic()
        self.next_due = time.time() + random.uniform(0, period_s)
        self.fault: str | None = None  # None | stuck | offset | dead | spike | drift
        self._stuck_payload: bytes | None = None
        self._fault_start = time.monotonic()   # when the timed fault begins
        self._fault_duration = FAULT_DURATION_S
        self._spikes = 0                       # spikes sent so far
        self.offset_on = False                 # read by the generators

    def frame(self, kit_id: int) -> RawFrame | None:
        if self.fault == "dead":
            return None
        t = time.monotonic() - self._fault_start      # seconds into the fault
        active = self.fault is not None and 0 <= t < self._fault_duration
        self.offset_on = active and self.fault == "offset"
        payload = self.gen(self)
        status = STATUS_SENSOR_OK
        if active and self.fault == "stuck":
            if self._stuck_payload is None:           # freeze the first faulty reading
                self._stuck_payload = payload
            payload = self._stuck_payload
            status |= STATUS_FAULT_INJECTED
        elif active and self.fault == "offset":
            status |= STATUS_FAULT_INJECTED
        elif (self.fault == "spike" and t >= 0
              and self._spikes < self._fault_duration // SPIKE_EVERY_S
              and t >= (self._spikes + 1) * SPIKE_EVERY_S):
            self._spikes += 1                         # at 10 s, 20 s, ... of the fault
            payload = _bump_first(payload, SPIKE_RAW)
            status |= STATUS_FAULT_INJECTED           # only the spiked readings are wrong
        elif active and self.fault == "drift":
            payload = _bump_first(payload, int(t // DRIFT_STEP_S) * DRIFT_STEP_RAW)
            status |= STATUS_FAULT_INJECTED
        self.seq = (self.seq + 1) & 0xFFFF
        return RawFrame(
            kit_id=kit_id, sensor_type_id=self.type_id, schema_version=1,
            seq=self.seq, tick_ms=int((time.monotonic() - self.boot) * 1000),
            status=status, payload=payload, rx_time=time.time(), rssi=-60,
            mac=self.mac,
        )


def _u16(*vals):
    return struct.pack("<" + "H" * len(vals), *[max(0, min(0xFFFF, int(v))) for v in vals])


def _i16(v):
    return struct.pack("<h", max(-32768, min(32767, int(v))))


def _gen_ds18b20(s):
    t = _diurnal(26.0, 4.0) + random.gauss(0, 0.06)
    if s.offset_on:
        t += 3.0
    return _i16(t * 100)


def _gen_bme688(s):
    t = _diurnal(27.0, 3.5) + random.gauss(0, 0.1)
    rh = _diurnal(55.0, 10.0, 0.5) + random.gauss(0, 0.5)
    p = 1008.0 + random.gauss(0, 0.4)
    iaq = max(10.0, _diurnal(60.0, 25.0, 0.25) + random.gauss(0, 3))
    eco2 = 400 + iaq * 6 + random.gauss(0, 15)
    bvoc = max(0.0, iaq / 40 + random.gauss(0, 0.05))
    return (_i16(t * 100) + _u16(rh * 100) + _u16(p * 10) + _u16(iaq * 10)
            + _u16(eco2) + _u16(bvoc * 100))


def _gen_pir(s):
    occupied_hours = 8 / 24 < (time.time() % 86400) / 86400 < 19 / 24
    motion = 1 if (occupied_hours and random.random() < 0.35) else 0
    s.__dict__.setdefault("events", 0)
    s.events += motion
    return bytes([motion]) + _u16(s.events)


def _gen_420ma(s):
    wind = max(0.0, _diurnal(4.0, 3.0, 0.3) + random.gauss(0, 0.8))
    ma = 4.0 + (wind / 30.0) * 16.0
    if s.offset_on:
        ma = 0.2  # broken-loop demonstration: below live zero
    return _u16(ma * 100) + _i16(wind * 100)


def _gen_rs485(s):
    v = 230.0 + random.gauss(0, 1.5)
    p = max(0.0, _diurnal(400.0, 350.0, 0.1) + random.gauss(0, 20))
    s.__dict__.setdefault("kwh", 1200.0)
    s.kwh += p * s.period_s / 3.6e6
    return _u16(v * 100) + _u16(p) + struct.pack("<I", int(s.kwh * 100))


def _gen_scd41(s):
    occupied = 9 / 24 < (time.time() % 86400) / 86400 < 18 / 24
    base = 850 if occupied else 460
    co2 = base + random.gauss(0, 25)
    t = _diurnal(26.5, 3.0) + random.gauss(0, 0.1)
    rh = 52 + random.gauss(0, 1)
    return _u16(co2) + _i16(t * 100) + _u16(rh * 100)


def _gen_veml7700(s):
    lux = max(0.0, _diurnal(15000, 25000, -0.25))
    if s.offset_on:
        lux *= 0.05  # smeared window
    return struct.pack("<I", int(lux * 100))


def _gen_spl(s):
    occupied = 9 / 24 < (time.time() % 86400) / 86400 < 18 / 24
    db = (52 if occupied else 34) + random.gauss(0, 2.5)
    return _u16(db * 10)


def _gen_jsn(s):
    level_pct = _diurnal(0.55, 0.25, 0.6)
    dist_mm = 300 + (1.0 - level_pct) * 1500 + random.gauss(0, 4)
    return _u16(dist_mm)


def _gen_reed(s):
    s.__dict__.setdefault("state", 0)
    s.__dict__.setdefault("count", 0)
    if random.random() < 0.02:
        s.state ^= 1
        s.count += 1
    return bytes([s.state]) + _u16(s.count)


def _gen_sct013(s):
    running = _diurnal(1.0, 1.0, 0.1) > 1.0
    irms = (8.4 if running else 0.08) + random.gauss(0, 0.15)
    va = 230.0 * max(0.0, irms)
    return _u16(irms * 1000) + _u16(va)


def _gen_sen0193(s):
    s.__dict__.setdefault("moisture", 62.0)
    s.moisture = max(8.0, s.moisture - 0.002 * s.period_s + random.gauss(0, 0.05))
    raw_mv = 2800 - s.moisture / 100 * 1600
    return _u16(raw_mv) + _u16(s.moisture * 10)


def _gen_water(s):
    wet = 1 if s.offset_on else 0
    raw_mv = 150 if wet else 3100
    return bytes([wet]) + _u16(raw_mv)


def _gen_at42(s):
    present = 1 if random.random() < 0.6 else 0
    s.__dict__.setdefault("count", 0)
    s.count += present and random.random() < 0.05
    return bytes([present]) + _u16(s.count)


GENERATORS = {
    1: (5.0, _gen_ds18b20), 2: (5.0, _gen_bme688), 3: (2.0, _gen_pir),
    4: (5.0, _gen_420ma), 5: (10.0, _gen_rs485), 6: (5.0, _gen_scd41),
    7: (5.0, _gen_veml7700), 8: (2.0, _gen_spl), 9: (5.0, _gen_jsn),
    10: (2.0, _gen_reed), 11: (2.0, _gen_sct013), 12: (10.0, _gen_sen0193),
    13: (5.0, _gen_water), 14: (2.0, _gen_at42),
}


def sim_mac(kit_id: int, type_id: int, n: int = 1) -> str:
    """Fake MAC for simulated node n of a type: 02:00:00:<kit>:<type>:<n>.
    02 marks a locally administered address, so it never matches real hardware."""
    return f"02:00:00:{kit_id & 0xFF:02X}:{type_id & 0xFF:02X}:{n & 0xFF:02X}"


class SimulatedSource:
    """Drop-in replacement for BleSource: same run(on_frame) contract.

    twins: type IDs that get a second node under the same kit ID, so two
    devices of one type can be tested without hardware."""

    def __init__(self, kit_id: int = 1, types: list[int] | None = None,
                 speedup: float = 1.0, twins: list[int] | None = None):
        self.kit_id = kit_id
        self.sims = [
            _Sim(tid, period / speedup, gen, sim_mac(kit_id, tid, n))
            for tid, (period, gen) in GENERATORS.items()
            if types is None or tid in types
            for n in ((1, 2) if tid in (twins or ()) else (1,))
        ]

    def inject_fault(self, type_id: int, fault: str | None,
                     delay_s: float = FAULT_DELAY_S,
                     duration_s: float = FAULT_DURATION_S) -> None:
        """Timed faults start after delay_s of normal readings and last
        duration_s; "dead" starts at once and never ends."""
        for s in self.sims:
            if s.type_id == type_id:
                s.fault = fault
                s._stuck_payload = None
                s._fault_start = time.monotonic() + delay_s
                s._fault_duration = duration_s
                s._spikes = 0

    async def run(self, on_frame) -> None:
        while True:
            now = time.time()
            for s in self.sims:
                if now >= s.next_due:
                    s.next_due = now + s.period_s
                    frame = s.frame(self.kit_id)
                    if frame is not None:
                        on_frame(frame)
            await asyncio.sleep(0.05)

    def tick_once(self, on_frame) -> None:
        """Synchronous single pass for tests: emit one frame per simulator."""
        for s in self.sims:
            frame = s.frame(self.kit_id)
            if frame is not None:
                on_frame(frame)
