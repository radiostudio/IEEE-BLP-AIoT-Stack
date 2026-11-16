"""Deterministic edge rule engine. No LLM in this path, ever.

Rules are JSON files in rules.d/. The agent may author them (deploy_rule
tool), but a rule only runs after a human approves it: deploy_rule writes
`<name>.json.pending`; `python -m gateway approve-rule <name>` renames it to
`<name>.json`. The engine loads only approved files.

Live reload, no restart needed: at most every RELOAD_CHECK_S, when a frame
arrives, the engine compares the name, change time and size of every
rules.d/*.json with the last check (.pending drafts never match *.json). If
anything was added, edited or deleted, it reloads all rules. A rule whose
content is unchanged keeps its timers and cooldown; an edited or deleted one
loses them. A file that fails to parse or to pass validate_rule_spec does
not run, and its exact error is printed.

Stale data: a sensor value older than STALE_S (arrival time) counts as no
data, so a condition on it is false. Every STALE_CHECK_S, also when no frame
arrives at all, the engine switches off once every relay kit of a rule that
uses a sensor gone stale, and logs it; it logs again when data returns.
Without this, a sensor that stops sending (battery, range, crash) would keep
its last value forever and could hold a relay on.

Rule spec:
{
  "name": "corridor_lighting",
  "description": "lights on only when moving people need them",
  "when": {"all": [
    {"sensor": "1:7", "field": "lux", "op": "<", "value": 300, "for_s": 30},
    {"sensor": "1:3", "field": "motion", "op": "==", "value": 1, "within_s": 60}
  ]},
  "on_fault": "skip",              # skip | fire; skip = never act on bad data
  "action": {"type": "log", "message": "lights ON"},
  "cooldown_s": 300
}

Condition semantics:
- op: <, <=, >, >=, ==, !=  against the latest value of sensor.field
- mac (optional): only that device of the sensor uid counts. Without it the
  condition holds when any device under the uid meets it. Each device keeps
  its own latest value and timers, so two devices sharing a uid never reset
  each other, and a faulty one (on_fault skip) only blocks itself
- for_s: condition must have held continuously for this long
- within_s: condition must have been true at least once in this window
Action types: log (stdout + annotation), annotate, webhook (POST JSON to url),
relay ({"type": "relay", "kit_id": 3, "state": "on"|"off"}: sets the wanted
state on the actuator link, which keeps sending it over the UART),
gpio (no-op stub here; the Pi/Uno Q port maps it to a real pin driver).
"""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from pathlib import Path

from ..core import RULES_DIR, STATUS_SENSOR_OK
from ..mcp_server.tools.deploy_rule import validate_rule_spec

_OPS = {
    "<": lambda a, b: a < b, "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b, ">=": lambda a, b: a >= b,
    "==": lambda a, b: a == b, "!=": lambda a, b: a != b,
}


class _CondState:
    def __init__(self):
        self.true_since: float | None = None
        self.last_true: float | None = None


class RuleEngine:
    # how often (seconds) evaluate() looks for added, edited or deleted rule files
    RELOAD_CHECK_S = 2.0
    # a sensor value older than this (since it arrived) counts as no data
    STALE_S = 15.0
    # how often relay rules are checked for sensors gone stale
    STALE_CHECK_S = 1.0

    def __init__(self, store, rules_dir: str | Path = RULES_DIR, actuator=None):
        self.store = store
        self.actuator = actuator   # gateway.actuation.link.ActuatorLink, for relay actions
        self.rules_dir = Path(rules_dir)
        self.rules: list[dict] = []
        self._state: dict[tuple[str, int, str], _CondState] = {}
        self._last_fired: dict[str, float] = {}
        self._latest: dict[tuple[str, str, str], tuple[float, float, int]] = {}
        # (uid, field) -> macs seen, in arrival order
        self._macs: dict[tuple[str, str], dict[str, None]] = {}
        self.fired_log: list[dict] = []
        self._fingerprint: dict[str, tuple[int, int]] = {}
        self._last_check = time.time()
        # evaluate() runs on the scanner's thread, the stale check on its own
        self._lock = threading.RLock()
        self._stale: set[tuple[str, str, str]] = set()   # (uid, field, mac) now stale
        self.reload()
        if actuator is not None:
            threading.Thread(target=self._watch_stale, daemon=True,
                             name="rules-stale").start()

    def _rules_fingerprint(self) -> dict[str, tuple[int, int]]:
        """file name -> (change time, size) for every rules.d/*.json."""
        fp = {}
        for path in self.rules_dir.glob("*.json"):  # never matches .json.pending
            try:
                st = path.stat()
            except OSError:
                continue  # deleted while listing
            fp[path.name] = (st.st_mtime_ns, st.st_size)
        return fp

    def reload(self) -> None:
        self._fingerprint = self._rules_fingerprint()
        old = {r["name"]: r for r in self.rules}
        self.rules = []
        for path in sorted(self.rules_dir.glob("*.json")):
            try:
                with open(path, encoding="utf-8") as fh:
                    rule = json.load(fh)
                errors = validate_rule_spec(rule)
            except json.JSONDecodeError as exc:
                errors = [f"invalid JSON at line {exc.lineno}, "
                          f"column {exc.colno}: {exc.msg}"]
            except (AttributeError, TypeError):
                errors = ["not a rule: the file or its 'when' is the wrong shape"]
            except OSError as exc:
                errors = [f"cannot read the file: {exc}"]
            if errors:
                print(f"[rules] {path.name}: {'; '.join(errors)} "
                      f"(not running until the file is fixed)")
                continue
            self.rules.append(rule)
        # unchanged rules keep their timers; edited or removed ones start fresh
        new = {r["name"]: r for r in self.rules}
        for name, rule in old.items():
            if new.get(name) != rule:
                self._forget(name)
        print(f"[rules] active: {', '.join(new) or '(none)'}")

    def _forget(self, name: str) -> None:
        """Drop a rule's timers and cooldown."""
        self._last_fired.pop(name, None)
        for key in [k for k in self._state if k[0] == name]:
            del self._state[key]

    # The engine is fed by the pipeline; it keeps its own latest-value cache so
    # evaluation never blocks on database reads.
    def evaluate(self, sensor_uid: str, values: dict[str, float], status: int,
                 mac: str = "") -> None:
        with self._lock:
            now = time.time()
            if now - self._last_check >= self.RELOAD_CHECK_S:
                self._last_check = now
                if self._rules_fingerprint() != self._fingerprint:
                    print("[rules] rule files changed, reloading")
                    self.reload()
            for field, value in values.items():
                self._latest[(sensor_uid, field, mac)] = (value, now, status)
                self._macs.setdefault((sensor_uid, field), {})[mac] = None
            for rule in self.rules:
                self._eval_rule(rule, now)

    def _watch_stale(self) -> None:
        # its own timer: when a sensor stops, no frame arrives to run evaluate()
        while True:
            time.sleep(self.STALE_CHECK_S)
            with self._lock:
                self._check_stale(time.time())

    def _check_stale(self, now: float) -> None:
        """Switch off, once, the relay kits of rules whose sensor went stale."""
        kits: dict[tuple[str, str, str], set[int]] = {}   # sensor key -> relay kits
        for rule in self.rules:
            action = rule.get("action", {})
            if action.get("type") != "relay":
                continue
            for cond in rule["when"]["all"]:
                key = (cond["sensor"], cond["field"], (cond.get("mac") or "").upper())
                kits.setdefault(key, set()).add(int(action["kit_id"]))
        stale = set()
        for key in kits:
            uid, field, mac = key
            macs = [mac] if mac else list(self._macs.get((uid, field), ()))
            ages = [now - self._latest[(uid, field, m)][1]
                    for m in macs if (uid, field, m) in self._latest]
            if ages and min(ages) > self.STALE_S:   # never heard: nothing to undo
                stale.add(key)
        for uid, field, mac in sorted(stale - self._stale):
            ks = sorted(kits[(uid, field, mac)])
            print(f"[rules] no data from {uid}{' ' + mac if mac else ''} ({field}) "
                  f"for {self.STALE_S:.0f} s: kit{'s' if len(ks) > 1 else ''} "
                  f"{', '.join(map(str, ks))} -> OFF")
            for kit in ks:
                self.actuator.set_relay(kit, False)
        for uid, field, mac in sorted((self._stale - stale) & kits.keys()):
            print(f"[rules] data from {uid}{' ' + mac if mac else ''} ({field}) again")
        self._stale = stale

    def _eval_rule(self, rule: dict, now: float) -> None:
        name = rule.get("name", "unnamed")
        cooldown = rule.get("cooldown_s", 0)
        if now - self._last_fired.get(name, 0) < cooldown:
            return
        conds = rule.get("when", {}).get("all", [])
        if not conds:
            return
        for idx, cond in enumerate(conds):
            if not self._eval_cond(name, idx, cond, rule.get("on_fault", "skip"), now):
                return
        self._last_fired[name] = now
        self._fire(rule, now)

    def _eval_cond(self, rule_name: str, idx: int, cond: dict,
                   on_fault: str, now: float) -> bool:
        want = cond.get("mac")
        macs = ([want.upper()] if want
                else list(self._macs.get((cond["sensor"], cond["field"]), ())))
        held = False
        for mac in macs:  # every device, so each one's timers stay current
            held |= self._eval_device(rule_name, idx, cond, mac, on_fault, now)
        return held

    def _eval_device(self, rule_name: str, idx: int, cond: dict, mac: str,
                     on_fault: str, now: float) -> bool:
        st = self._state.setdefault((rule_name, idx, mac), _CondState())
        latest = self._latest.get((cond["sensor"], cond["field"], mac))
        if latest is None:
            return False
        value, ts, status = latest
        if now - ts > self.STALE_S:
            # no data lately: an old value must not switch a relay back on
            # after the stale check switched it off
            st.true_since = None
            return False
        if on_fault == "skip" and not (status & STATUS_SENSOR_OK):
            # bad data must never look like a decision input
            st.true_since = None
            return False
        is_true = _OPS[cond["op"]](value, cond["value"])
        if is_true:
            if st.true_since is None:
                st.true_since = now
            st.last_true = now
        else:
            st.true_since = None
        if "for_s" in cond:
            return st.true_since is not None and now - st.true_since >= cond["for_s"]
        if "within_s" in cond:
            return st.last_true is not None and now - st.last_true <= cond["within_s"]
        return is_true

    def _fire(self, rule: dict, now: float) -> None:
        action = rule.get("action", {"type": "log"})
        record = {"rule": rule.get("name"), "ts": now, "action": action.get("type")}
        self.fired_log.append(record)
        kind = action.get("type", "log")
        message = action.get("message", f"rule {rule.get('name')} fired")
        if kind in ("log", "annotate"):
            print(f"[rule:{rule.get('name')}] {message}")
            self.store.annotate(f"[rule:{rule.get('name')}] {message}",
                                author="rule-engine", ts=now)
        elif kind == "webhook":
            try:
                req = urllib.request.Request(
                    action["url"],
                    data=json.dumps(record).encode(),
                    headers={"Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=5)
            except Exception as exc:
                print(f"[rule:{rule.get('name')}] webhook failed: {exc}")
        elif kind == "relay":
            # only sets the wanted state; the actuator link keeps sending it
            if self.actuator is None:
                print(f"[rule:{rule.get('name')}] relay action skipped: "
                      f"no actuator link in this gateway")
            else:
                self.actuator.set_relay(int(action["kit_id"]),
                                        action["state"] == "on")
        elif kind == "gpio":
            # Port point: on Raspberry Pi / Uno Q, replace this stub with a
            # gpiozero/libgpiod driver. The rule spec does not change.
            print(f"[rule:{rule.get('name')}] gpio stub: "
                  f"pin={action.get('pin')} state={action.get('state')}")
