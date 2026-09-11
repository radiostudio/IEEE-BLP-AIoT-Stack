"""Ingest pipeline: frames in, validated rows and rule evaluations out.

scanner (BLE or simulator) -> dedupe -> card decode -> reconcile -> store
                                                        -> rule engine
"""

from __future__ import annotations

from .core import RawFrame
from .decoder.reconcile import Reconciler
from .decoder.registry import CardRegistry
from .scanner.dedupe import Deduper
from .store.db import Store


class Pipeline:
    def __init__(self, store: Store, registry: CardRegistry | None = None,
                 rule_engine=None):
        self.store = store
        self.registry = registry or CardRegistry()
        self.deduper = Deduper()
        self.reconciler = Reconciler()
        self.rule_engine = rule_engine
        self.frames_in = 0
        self.frames_stored = 0
        self._announced: set[str] = set()

    def on_frame(self, frame: RawFrame) -> None:
        self.frames_in += 1
        if not self.deduper.accept(frame):
            return
        card, values = self.registry.decode(frame)
        if frame.uid not in self._announced:
            self._announced.add(frame.uid)
            pretty = "  ".join(f"{k}={v:.2f}" for k, v in values.items())
            print(f"[gateway] {frame.uid} ({card.part if card else 'no card'}) "
                  f"online: {pretty}")
        recon = self.reconciler.observe(frame)
        self.store.upsert_sensor(
            frame.uid, frame.kit_id, frame.sensor_type_id, frame.schema_version,
            card.part if card else None, frame.status, recon["lost_since_last"])
        if values:
            self.store.insert_readings(
                frame.uid, recon["corrected_time"], frame.rx_time,
                frame.seq, frame.status, values)
            self.frames_stored += 1
        if self.rule_engine is not None:
            self.rule_engine.evaluate(frame.uid, values, frame.status)
