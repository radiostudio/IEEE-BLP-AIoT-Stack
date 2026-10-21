"""Relay actuator card + command frame checks. Run: python -m gateway.tests.test_relay_command"""

from __future__ import annotations

from ..core import RELAY_ACTUATOR_TYPE_ID, build_relay_command, parse_manufacturer_data
from ..decoder.registry import CardRegistry


def test_card_registered():
    card = next((c for c in CardRegistry().all_cards()
                 if c.sensor_type_id == RELAY_ACTUATOR_TYPE_ID), None)
    assert card is not None and card.doc.get("role") == "actuator"
    assert card.measurands == []          # a command card reports nothing


def test_command_roundtrip():
    for on in (True, False):
        data = build_relay_command(kit_id=1, on=on, seq=0x1234, tick_ms=5000)
        f = parse_manufacturer_data(data)
        assert (f.kit_id, f.sensor_type_id, f.schema_version, f.seq) == (1, 18, 1, 0x1234)
        assert f.payload == bytes([1 if on else 0])


def test_known_bytes():
    # the exact bytes documented in the firmware README for the nRF Connect test
    data = build_relay_command(kit_id=1, on=True, seq=1, tick_ms=0)
    assert data.hex().upper() == "0100120101000000000001" + "01", data.hex()
    # fits the 31-byte legacy adv budget: flags(3) + AD hdr(2) + company(2) + data(12)
    assert 3 + 2 + 2 + len(data) <= 31


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"  ok: {name}")
