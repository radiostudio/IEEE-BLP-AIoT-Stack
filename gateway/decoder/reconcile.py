"""Time reconciliation and delivery accounting.

Advertisements are unacknowledged broadcast. Two consequences the gateway must
repair before any cross-sensor analysis is trustworthy:

- Packet loss is silent. The per-frame `seq` counter exposes it; this module
  turns seq gaps into a delivery ratio per sensor.
- Arrival time carries BLE scan-window jitter. The per-frame monotonic
  `tick_ms` does not. We estimate the per-sensor offset between tick time and
  wall clock with a rolling minimum-jitter estimate, then stamp each reading
  with the corrected time. Correlations between sensors are computed on
  corrected time, never raw arrival time.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core import RawFrame

_SEQ_MOD = 65536


@dataclass
class _SensorTrack:
    last_seq: int | None = None
    rx_count: int = 0
    lost_count: int = 0
    # offset = rx_time - tick_s; the minimum over a window approximates the
    # true offset because jitter only ever adds delay, never removes it.
    offsets: list[float] = field(default_factory=list)
    boot_epoch: float | None = None

    def delivery_ratio(self) -> float:
        total = self.rx_count + self.lost_count
        return self.rx_count / total if total else 1.0


class Reconciler:
    WINDOW = 64

    def __init__(self):
        self._tracks: dict[str, _SensorTrack] = {}

    def observe(self, frame: RawFrame) -> dict:
        t = self._tracks.setdefault(frame.uid, _SensorTrack())
        lost = 0
        if t.last_seq is not None:
            gap = (frame.seq - t.last_seq) % _SEQ_MOD
            if gap == 0:
                gap = 1  # duplicate slipped past dedupe; count as one delivery
            lost = gap - 1
            if lost > 1000:
                # SIM rebooted (seq restarted): not loss, reset tracking
                lost = 0
                t.offsets.clear()
        t.last_seq = frame.seq
        t.rx_count += 1
        t.lost_count += lost

        tick_s = frame.tick_ms / 1000.0
        offset = frame.rx_time - tick_s
        if t.offsets and abs(offset - min(t.offsets)) > 30:
            # tick clock jumped (device-side reset independent of seq):
            # stale pre-jump offsets would otherwise win min() for a full
            # window's worth of frames, dragging corrected_time far behind.
            t.offsets.clear()
        t.offsets.append(offset)
        if len(t.offsets) > self.WINDOW:
            del t.offsets[: len(t.offsets) - self.WINDOW]
        t.boot_epoch = min(t.offsets)
        corrected = t.boot_epoch + tick_s

        return {
            "corrected_time": corrected,
            "jitter_removed_s": frame.rx_time - corrected,
            "lost_since_last": lost,
            "delivery_ratio": t.delivery_ratio(),
        }

    def stats(self) -> dict[str, dict]:
        return {
            uid: {
                "rx_count": t.rx_count,
                "lost_count": t.lost_count,
                "delivery_ratio": round(t.delivery_ratio(), 4),
            }
            for uid, t in self._tracks.items()
        }
