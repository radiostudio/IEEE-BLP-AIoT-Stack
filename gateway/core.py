"""Shared frame model, payload spec constants, and configuration.

BLE Manufacturer Specific Data layout (after the 2-byte company ID):

    offset  size  field
    0       2     kit_id          uint16 LE
    2       1     sensor_type_id  uint8
    3       1     schema_version  uint8
    4       2     seq             uint16 LE (wraps at 65535)
    6       4     tick_ms         uint32 LE (monotonic since SIM boot)
    10      1     status          bit0 sensor_ok, bit1 low_batt, bit2 fault_injected
    11      n     payload         per sensor card, n <= 12
"""

from __future__ import annotations

import json
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path

COMPANY_ID = 0xFFFF
HEADER = struct.Struct("<HBBHIB")
HEADER_LEN = HEADER.size  # 11

STATUS_SENSOR_OK = 0x01
STATUS_LOW_BATT = 0x02
STATUS_FAULT_INJECTED = 0x04

PACKAGE_DIR = Path(__file__).resolve().parent
CARDS_DIR = PACKAGE_DIR / "cards"
RULES_DIR = PACKAGE_DIR / "rules" / "rules.d"
DEFAULT_CONFIG = PACKAGE_DIR / "config.json"


@dataclass
class RawFrame:
    kit_id: int
    sensor_type_id: int
    schema_version: int
    seq: int
    tick_ms: int
    status: int
    payload: bytes
    rx_time: float = field(default_factory=time.time)
    rssi: int | None = None

    @property
    def uid(self) -> str:
        return f"{self.kit_id}:{self.sensor_type_id}"

    @property
    def sensor_ok(self) -> bool:
        return bool(self.status & STATUS_SENSOR_OK)


def parse_manufacturer_data(data: bytes, rx_time: float | None = None,
                            rssi: int | None = None) -> RawFrame | None:
    """Parse the bytes that follow the company ID. Returns None on malformed frames."""
    if len(data) < HEADER_LEN:
        return None
    kit_id, type_id, schema, seq, tick_ms, status = HEADER.unpack(data[:HEADER_LEN])
    return RawFrame(
        kit_id=kit_id,
        sensor_type_id=type_id,
        schema_version=schema,
        seq=seq,
        tick_ms=tick_ms,
        status=status,
        payload=bytes(data[HEADER_LEN:]),
        rx_time=rx_time if rx_time is not None else time.time(),
        rssi=rssi,
    )


def build_manufacturer_data(frame: RawFrame) -> bytes:
    """Inverse of parse_manufacturer_data; used by the simulator and by tests."""
    head = HEADER.pack(frame.kit_id, frame.sensor_type_id, frame.schema_version,
                       frame.seq & 0xFFFF, frame.tick_ms & 0xFFFFFFFF, frame.status)
    return head + frame.payload


RELAY_ACTUATOR_TYPE_ID = 18  # gateway/cards/18_relay_actuator.json


def build_relay_command(kit_id: int, on: bool, seq: int, tick_ms: int,
                        schema_version: int = 1) -> bytes:
    """Manufacturer data (WITHOUT the company ID) for a relay command frame.

    Same header as every sensor frame; payload is one byte, relay_state.
    """
    return build_manufacturer_data(RawFrame(
        kit_id=kit_id, sensor_type_id=RELAY_ACTUATOR_TYPE_ID,
        schema_version=schema_version, seq=seq, tick_ms=tick_ms,
        status=STATUS_SENSOR_OK, payload=bytes([1 if on else 0])))


def load_config(path: str | Path | None = None) -> dict:
    p = Path(path) if path else DEFAULT_CONFIG
    if p.exists():
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    return {
        "kit_id": None,
        "company_id": COMPANY_ID,
        "db_path": str(PACKAGE_DIR / "data" / "gateway.db"),
        "dashboard_port": 8931,
        "downsample_period_s": 300,
    }
