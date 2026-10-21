"""Reboot-aware PIR counter checks. Run: python -m gateway.tests.test_counters"""

from __future__ import annotations

from ..core import RawFrame
from ..decoder.counters import CounterTracker
from ..decoder.registry import CardRegistry


def _frame(tick_s: float, motion: int, count: int) -> RawFrame:
    payload = bytes([motion]) + count.to_bytes(2, "little")
    return RawFrame(kit_id=1, sensor_type_id=3, schema_version=1, seq=0,
                    tick_ms=int(tick_s * 1000), status=1, payload=payload)


def _run(frames):
    reg, trk = CardRegistry(), CounterTracker()
    out = []
    for f in frames:
        card, vals = reg.decode(f)
        out.append(trk.apply(f, card, vals))
    return [(int(v["motion"]), int(v["event_count"])) for v in out]


def test_reboot_keeps_count_rising():
    # the 13:29-13:30 sequence from the bench: count 2, node reboots, 0, 0, 3, 4
    got = _run([_frame(100, 1, 2), _frame(5, 1, 0), _frame(15, 1, 0),
                _frame(47, 1, 3), _frame(57, 1, 4)])
    counts = [c for _, c in got]
    assert counts == sorted(counts), counts
    # first frame after the reboot: PIR already high, firmware has not counted it
    assert got[1] == (1, 3), got
    assert got[-1][1] == 2 + 1 + 4, got


def test_motion_high_implies_count_at_least_one():
    for m, c in _run([_frame(1, 1, 0), _frame(3, 1, 0), _frame(5, 0, 0)]):
        assert m == 0 or c >= 1


def test_idle_node_stays_zero():
    assert [c for _, c in _run([_frame(1, 0, 0), _frame(3, 0, 0)])] == [0, 0]


def test_firmware_that_counts_boot_level_is_not_double_counted():
    # fixed firmware reports motion=1, count=1 on a high boot
    assert _run([_frame(1, 1, 1), _frame(3, 0, 1), _frame(9, 1, 2)]) == \
        [(1, 1), (0, 1), (1, 2)]


def test_uint16_wrap():
    counts = [c for _, c in _run([_frame(1, 0, 65534), _frame(3, 0, 65535),
                                  _frame(5, 1, 0), _frame(7, 1, 1)])]
    assert counts == [65534, 65535, 65536, 65537], counts


def test_stale_frame_is_not_a_reboot():
    counts = [c for _, c in _run([_frame(100, 0, 10), _frame(95, 0, 9),
                                  _frame(110, 0, 11)])]
    assert counts == [10, 9, 11], counts


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"  ok: {name}")
