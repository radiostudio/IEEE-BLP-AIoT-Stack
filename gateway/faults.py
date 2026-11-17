"""Live fault injection on real sensors, for QA.

`python -m gateway inject ...` checks a request and writes it to FAULTS_FILE
(request side). The running gateway (FaultInjector, applying side) reads that
file and changes the matching live readings right after decoding, so the
faulty value is the reading for everything downstream: storage, dashboards,
AI tools and rules. A changed reading gets the fault_injected status bit
(status 1 -> 5), the same truth bit the simulator sets; only the QA
dashboard reads it. A gateway restart clears all faults.

    inject 1:1 stuck --duration 60   repeat the value of that moment for 60 s
    inject 1:1 offset 3              live value + 3, until stop
    inject 1:1 spike                 the next reading = the card's maximum
    inject 1:1 drift 0.5             live + 0.5, + 1.0, + 1.5 ... per reading,
                                     held at the card's maximum (a negative
                                     drift: its minimum), until stop
    inject 1:1 stop                  end the fault on 1:1
    inject status                    list the requested faults

Each sensor has one value that can be injected, the one the QA dashboard
shows (SENSORS). One fault per sensor: a new one replaces it.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .core import PACKAGE_DIR

FAULTS_FILE = PACKAGE_DIR / "data" / "faults.json"
# only these sensors can be injected, each on the one value the QA dashboard shows
SENSORS = {
    "1:1": "temperature_c",   # DS18B20
    "1:17": "humidity_pct",   # SHT40
    "1:6": "co2_ppm",         # SCD41
    "1:2": "iaq",             # BME688
}
KINDS = ("stuck", "offset", "spike", "drift")


class FaultError(ValueError):
    """A request that is not valid; the message says why."""


def load(path: Path = FAULTS_FILE) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def save(faults: dict, path: Path = FAULTS_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(faults, indent=2), encoding="utf-8")
    os.replace(tmp, path)   # the gateway never reads a half-written file


def _card(registry, sensor: str):
    type_id = int(sensor.split(":")[1])
    return next((c for c in registry.all_cards() if c.sensor_type_id == type_id), None)


def _card_range(card, field: str) -> tuple[float, float]:
    m = next(m for m in card.measurands if m["name"] == field)
    return m["range"][0], m["range"][1]


def request(registry, sensor: str, kind: str, amount: float | None = None,
            duration: float | None = None, path: Path = FAULTS_FILE,
            now: float | None = None) -> str:
    """Check one request and store it; returns the line to print."""
    if sensor not in SENSORS:
        raise FaultError(f"sensor '{sensor}' cannot be injected: use {', '.join(SENSORS)}")
    card = _card(registry, sensor)
    field = SENSORS[sensor]
    key = f"{sensor}/{field}"
    kind = kind.strip().lower()   # STUCK, Stuck and stuck all work
    faults = load(path)

    if kind == "stop":
        if key not in faults:
            return f"no fault active on {sensor} {field}"
        del faults[key]
        save(faults, path)
        return f"stopped: {sensor} {field} (live values again)"

    if kind not in KINDS:
        raise FaultError(f"unknown fault '{kind}': use stuck, offset, spike, drift or stop")
    if kind == "stuck":
        if amount is not None:
            raise FaultError("stuck takes no number: it repeats the value of that moment")
        if duration is None or duration <= 0:
            raise FaultError(f"stuck needs --duration <seconds>, e.g. inject {sensor} stuck --duration 60")
    elif kind == "spike":
        if amount is not None or duration is not None:
            raise FaultError("spike takes no number and no --duration")
    else:  # offset, drift
        if amount is None or amount == 0:
            example = "3" if kind == "offset" else "0.5"
            raise FaultError(f"{kind} needs a number that is not 0, e.g. inject {sensor} {kind} {example}")
        if duration is not None:
            raise FaultError(f"{kind} runs until 'inject {sensor} stop'; it takes no --duration")

    entry = {"sensor": sensor, "field": field, "fault": kind,
             "requested_at": time.time() if now is None else now}
    if kind == "stuck":
        entry["duration_s"] = duration
    if kind in ("offset", "drift"):
        entry["amount"] = amount
    old = faults.get(key)
    faults[key] = entry
    save(faults, path)

    low, top = _card_range(card, field)
    if kind == "stuck":
        what = f"the value of this moment repeats for {duration:g} s, then live values"
    elif kind == "offset":
        what = f"live value {amount:+g}, until 'inject {sensor} stop'"
    elif kind == "spike":
        what = f"the next reading = {top:g} (card maximum), then live values"
    else:   # drift: a rising drift stops at the card maximum, a falling one at the minimum
        limit = f"{top:g} (card maximum)" if amount > 0 else f"{low:g} (card minimum)"
        what = (f"live value {amount:+g}, {2 * amount:+g}, {3 * amount:+g} ... per reading, "
                f"held at {limit}, until 'inject {sensor} stop'")
    replaced = f" (replaces the {old['fault']})" if old else ""
    return f"{kind} on {sensor} {field}: {what}{replaced}"


def status(path: Path = FAULTS_FILE, now: float | None = None) -> str:
    now = time.time() if now is None else now
    lines = []
    for f in load(path).values():
        line = f"{f['sensor']} {f['field']}: {f['fault']}"
        if f["fault"] == "stuck":
            left = f["requested_at"] + f["duration_s"] - now
            if left <= 0:
                continue   # already over
            line += f", {left:.0f} s left"
        elif f["fault"] in ("offset", "drift"):
            line += f" {f['amount']:+g}{' per reading' if f['fault'] == 'drift' else ''}, until stop"
        elif now - f["requested_at"] > SPIKE_WINDOW_S:
            continue   # a spike is one reading: long done
        else:
            line += " (on the next reading)"
        lines.append(line)
    return "\n".join(lines) or "no faults active"


# -- applying side (runs inside the gateway) ---------------------------------

SPIKE_WINDOW_S = 15.0   # status shows a spike as waiting this long after the request


class _State:
    """What one active fault has done so far (lives only in the gateway)."""

    def __init__(self, entry: dict):
        self.entry = entry
        self.frozen: float | None = None    # stuck: the repeated value
        self.readings = 0                   # drift: readings since it began
        self.held: float | None = None      # drift: amount kept once saturated
        self.done = False                   # spike sent / stuck over
        self.started = False                # "start" written to the journal


class FaultInjector:
    """Changes live readings of sensors with a requested fault. Re-reads
    FAULTS_FILE at most every CHECK_S; a stopped or replaced fault ends at
    once. Only one thread (the scanner's) calls apply().

    apply() also says whether it changed a reading; the pipeline then sets
    the fault_injected status bit on it (status 1 -> 5), which the QA
    dashboard's answer timeline reads. Each fault's start (first changed
    reading) and end also go to the store's journal (author JOURNAL_AUTHOR),
    for the answer row's table of exact times."""

    CHECK_S = 1.0
    JOURNAL_AUTHOR = "fault-injector"

    def __init__(self, registry, path: Path = FAULTS_FILE, store=None):
        self.registry = registry
        self.path = path
        self.store = store
        self._active: dict[str, _State] = {}
        self._last_check = 0.0
        for key, entry in load(path).items():   # left over from before a restart
            self._note(entry, "end", key, "(gateway restart)")
        save({}, path)   # a gateway restart ends every fault

    def _note(self, entry: dict, verb: str, key: str, detail: str = "",
              ts: float | None = None) -> None:
        if self.store is not None:
            note = f"{verb} {entry['fault']} {key.split('/', 1)[1]} {detail}".strip()
            self.store.annotate(note, sensor_uid=entry["sensor"],
                                author=self.JOURNAL_AUTHOR, ts=ts)

    def apply(self, uid: str, values: dict[str, float],
              now: float | None = None) -> tuple[dict, bool]:
        """(values, faulted): the readings with any active fault applied, and
        whether a fault changed one of them."""
        now = time.time() if now is None else now
        if now - self._last_check >= self.CHECK_S:
            self._last_check = now
            self._refresh(now)
        out, faulted = values, False
        for key, st in self._active.items():
            sensor, field = key.split("/", 1)
            if sensor != uid or field not in values or st.done:
                continue
            changed = self._change(key, st, values[field], now)
            if changed is None:   # the fault just ended: this reading is live
                continue
            if out is values:
                out = dict(values)
            out[field], faulted = changed, True
        return out, faulted

    def _refresh(self, now: float) -> None:
        wanted = load(self.path)
        for key in list(self._active):
            if wanted.get(key) != self._active[key].entry:
                st = self._active.pop(key)
                if not st.done:   # stopped or replaced before it ended
                    print(f"[fault] {st.entry['fault']} on {key.replace('/', ' ')} ended "
                          f"(live values again)")
                    if st.started:
                        self._note(st.entry, "end", key, ts=now)
        for key, entry in wanted.items():
            if key not in self._active:
                self._active[key] = _State(entry)

    def _change(self, key: str, st: _State, live: float, now: float) -> float | None:
        """The faulty value for this reading, or None once the fault is over."""
        e, name = st.entry, key.replace("/", " ")
        low, top = _card_range(_card(self.registry, e["sensor"]), e["field"])
        kind = e["fault"]
        if not st.started:
            st.started = True
            detail = {"stuck": f"({e.get('duration_s', 0):g} s)", "spike": f"({top:g})",
                      "offset": f"({e.get('amount', 0):+g})",
                      "drift": f"({e.get('amount', 0):+g} per reading)"}[kind]
            self._note(e, "start", key, detail, ts=now)
        if kind == "stuck":
            if now >= e["requested_at"] + e["duration_s"]:
                st.done = True
                print(f"[fault] stuck on {name} ended after {e['duration_s']:g} s (live values again)")
                self._note(e, "end", key, ts=now)
                return None
            if st.frozen is None:
                st.frozen = live
                print(f"[fault] stuck on {name}: repeating {live:g} for {e['duration_s']:g} s")
            return st.frozen
        if kind == "offset":
            return live + e["amount"]
        if kind == "spike":
            st.done = True
            print(f"[fault] spike on {name}: {top:g} (card maximum), then live values")
            self._note(e, "end", key, ts=now + 1)   # one reading: shown as 1 s on the timeline
            return top
        # drift: one more step per reading, until live + drift meets the card
        # limit; then that amount is kept, so live variations still show
        if st.held is not None:
            return live + st.held
        st.readings += 1
        total = st.readings * e["amount"]
        limit = top if e["amount"] > 0 else low
        if (e["amount"] > 0 and live + total >= limit) or (e["amount"] < 0 and live + total <= limit):
            st.held = limit - live
            print(f"[fault] drift on {name} reached {limit:g} (card "
                  f"{'maximum' if e['amount'] > 0 else 'minimum'}): holding")
            return limit
        return live + total
