"""Advertisement de-duplication.

A SIM repeats each advertisement many times within its interval so that at
least one copy survives the scan window. Downstream must see each (kit, type,
mac, seq) exactly once; the mac keeps two nodes that share a kit ID and type
from dropping each other's frames.
"""

from __future__ import annotations

from ..core import RawFrame


class Deduper:
    def __init__(self, horizon: int = 8):
        # horizon: how many recent seq values to remember per sensor; repeats
        # arrive in bursts, so a short memory is enough and bounds RAM.
        self.horizon = horizon
        self._seen: dict[str, list[int]] = {}

    def accept(self, frame: RawFrame) -> bool:
        recent = self._seen.setdefault(frame.device_key, [])
        if frame.seq in recent:
            return False
        recent.append(frame.seq)
        if len(recent) > self.horizon:
            del recent[: len(recent) - self.horizon]
        return True
