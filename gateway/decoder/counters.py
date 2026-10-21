"""Reboot-aware event counters.

Some sensors (PIR, reed, touch) report a cumulative event count that lives in
RAM on the node: it restarts at 0 on every reboot and wraps at 65535. Stored
raw, the count drops on a reboot and the dashboard shows an activity history
that goes backwards.

A card opts a measurand in with a "counter" block:

    "counter": {"scope": "since_boot", "level_field": "motion"}

`scope` says the raw value counts events since the node booted. The optional
`level_field` names a 0/1 level measurand in the same frame (the PIR's
`motion`). Older firmware seeds its level from the pin at boot without
counting it, so a PIR that is already high at power-up reports motion=1 with
event_count=0. When the first frame of a boot shows that, the pending event is
counted so the invariant "motion=1 implies at least one event" holds.

`CounterTracker.apply` returns the frame's values with those measurands
replaced by a series that keeps rising across node reboots and counter wraps.
State is in memory: after a gateway restart the series re-baselines at the
node's current raw count.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core import RawFrame

_WRAP = 1 << 16
# tick_ms is monotonic since node boot. A regression bigger than this is a
# reboot; a smaller one is a stale frame delivered out of order, not a reboot.
_REBOOT_TICK_DROP_MS = 10_000


@dataclass
class _Track:
    last_tick: int
    last_raw: int
    offset: int      # events accumulated before the current boot / wrap
    bias: int        # 1 when the boot-time level was high but never counted
    last_out: int


class CounterTracker:
    def __init__(self):
        self._tracks: dict[tuple[str, str], _Track] = {}

    def apply(self, frame: RawFrame, card, values: dict[str, float]) -> dict[str, float]:
        out = dict(values)
        for m in card.measurands:
            spec = m.get("counter")
            name = m["name"]
            if not spec or name not in values:
                continue
            raw = int(values[name])
            level = values.get(spec.get("level_field", ""), 0)
            key = (frame.uid, name)
            t = self._tracks.get(key)

            if t is None:
                t = _Track(frame.tick_ms, raw, 0, int(bool(level) and raw == 0), 0)
            elif frame.tick_ms + _REBOOT_TICK_DROP_MS < t.last_tick:
                # node rebooted: carry everything counted so far into the offset
                t = _Track(frame.tick_ms, raw, t.last_out, int(bool(level) and raw == 0), 0)
            elif frame.tick_ms < t.last_tick:
                # stale frame arriving late: report it but don't move the state
                out[name] = float(t.offset + t.bias + raw)
                continue
            else:
                if raw < t.last_raw:
                    t.offset += _WRAP   # uint16 wrap within one boot
                t.last_tick, t.last_raw = frame.tick_ms, raw

            t.last_out = t.offset + t.bias + raw
            self._tracks[key] = t
            out[name] = float(t.last_out)
        return out
