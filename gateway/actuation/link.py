"""UART link to the actuation gateway (UNO Q), which broadcasts relay commands.

Messages are one JSON object per line, both ways, matched by "id":

    gateway -> actuator                                actuator -> gateway
    {"id": 1, "cmd": "hello"}                          {"id": 1, "ok": true, "role": "actuator"}
    {"id": 2, "cmd": "ping"}                           {"id": 2, "ok": true}
    {"id": 3, "cmd": "relay", "kit_id": 3, "state": "on"}
                                                       {"id": 3, "ok": true}  or
                                                       {"id": 3, "ok": false, "error": "..."}

Finding the port: every USB serial port is tried with "hello"; the one that
answers role "actuator" is used. Clone adapters on this kit share one serial
number, so a fixed /dev/serial/by-id path cannot tell them apart.

Keep-alive: rules only change the wanted state per kit. Every SEND_EVERY_S
the worker re-sends ON for every kit that should be on (OFF a few times after
a kit is switched off, a ping when nothing is on). The actuator switches a
kit off when its ON stops arriving, so a lost cable or a stopped gateway
turns every load off; after reconnecting, the current wanted state is sent
again. Commands are never queued while the link is down.
"""

from __future__ import annotations

import glob
import json
import threading
import time

BAUD = 115200             # 8N1; the actuator script must use the same
PORT_PATTERNS = ("/dev/ttyUSB*", "/dev/ttyACM*")
SCAN_EVERY_S = 3.0        # look for the actuator again after this long
SEND_EVERY_S = 5.0        # keep-alive round
REPLY_TIMEOUT_S = 2.0     # wait for each reply
HELLO_TIMEOUT_S = 1.0     # wait for "hello" while probing a port
MISSES_BEFORE_LOST = 2    # missing replies in a row that mean the link is gone
OFF_REPEATS = 3           # rounds that send OFF after a kit is switched off
STATUS_EVERY_S = 60.0     # status line while searching or connected


def log(text: str) -> None:
    print(f"[actuator] {text}")


class ActuatorLink:
    def __init__(self):
        self._on: set[int] = set()            # kits that should be ON
        self._off_left: dict[int, int] = {}   # kit -> OFF sends still to do
        self._lock = threading.Lock()
        self._wake = threading.Event()        # a state change: send now
        self._ser = None
        self._port: str | None = None         # the connected port
        self._buf = b""
        self._next_id = 0
        self._misses = 0
        self._last_status = 0.0
        self._sent = self._missed = 0         # since the last status line

    def start(self) -> None:
        log(f"searching for the actuator on {', '.join(PORT_PATTERNS)} at {BAUD} baud")
        threading.Thread(target=self._run, daemon=True, name="actuator-link").start()

    def set_relay(self, kit_id: int, on: bool) -> None:
        """Change the wanted state. Never waits for the UART."""
        with self._lock:
            changed = (kit_id in self._on) != on
            if on:
                self._on.add(kit_id)
                self._off_left.pop(kit_id, None)
            else:
                self._on.discard(kit_id)
                self._off_left[kit_id] = OFF_REPEATS
        if changed:
            log(f"kit {kit_id} -> {'ON' if on else 'OFF'}")
        self._wake.set()

    # -- worker ------------------------------------------------------------

    def _run(self) -> None:
        try:
            import serial  # noqa: F401  (pyserial)
        except ImportError:
            log("pyserial is not installed (pip install pyserial); "
                "relay actions will not reach the actuator")
            return
        while True:
            if self._ser is None and not self._find():
                time.sleep(SCAN_EVERY_S)
                continue
            self._round()
            self._status()
            self._wake.wait(SEND_EVERY_S)
            self._wake.clear()

    def _status(self) -> None:
        """While connected, one line every STATUS_EVERY_S."""
        now = time.monotonic()
        if self._ser is None or now - self._last_status < STATUS_EVERY_S:
            return
        self._last_status = now
        with self._lock:
            on = sorted(self._on)
        log(f"link OK on {self._port}: kits ON {on}, "
            f"{self._sent} sent, {self._missed} missed")
        self._sent = self._missed = 0

    def _find(self) -> bool:
        """Try every USB serial port; log what was found on each attempt."""
        ports = sorted(p for pattern in PORT_PATTERNS for p in glob.glob(pattern))
        results = []
        for port in ports:
            result = self._probe(port)
            if result == "actuator":
                self._port, self._misses = port, 0
                self._sent = self._missed = 0
                self._last_status = time.monotonic()
                log(f"connected on {port}")
                return True
            results.append(f"{port} {result}")
        found = "; ".join(results) or "no USB serial port is connected"
        log(f"searching: actuator not found ({found}). "
            f"Checking again in {SCAN_EVERY_S:.0f} s")
        return False

    def _probe(self, port: str) -> str:
        """"actuator" (port left open as the link), or why it is not."""
        ser = self._open(port)
        if ser is None:
            return "could not be opened (in use by another program?)"
        self._ser, self._buf = ser, b""
        try:
            reply = self._exchange({"cmd": "hello"}, HELLO_TIMEOUT_S)
        except OSError:   # serial.SerialException is an OSError
            reply = None
        if reply and reply.get("ok") and reply.get("role") == "actuator":
            return "actuator"
        ser.close()
        self._ser = None
        return "did not answer as the actuator"

    def _open(self, port: str):
        import serial
        ser = serial.Serial()
        ser.port, ser.baudrate = port, BAUD
        ser.timeout, ser.write_timeout = 0.1, 1.0
        ser.dtr = ser.rts = False   # opening must not reset a board on the port
        ser.exclusive = True        # skip a port another program holds
        try:
            ser.open()
        except (OSError, ValueError):
            return None
        return ser

    def _round(self) -> None:
        with self._lock:
            msgs = [{"cmd": "relay", "kit_id": k, "state": "on"}
                    for k in sorted(self._on)]
            for k in sorted(self._off_left):
                msgs.append({"cmd": "relay", "kit_id": k, "state": "off"})
                self._off_left[k] -= 1
                if self._off_left[k] <= 0:
                    del self._off_left[k]
        for msg in msgs or [{"cmd": "ping"}]:
            try:
                reply = self._exchange(msg, REPLY_TIMEOUT_S)
            except OSError as exc:
                # Linux reports the port itself as broken
                self._lost(f"port {self._port} failed (adapter unplugged or broken?): {exc}")
                return
            self._sent += 1
            if reply is None:
                self._missed += 1
                self._misses += 1
                if self._misses >= MISSES_BEFORE_LOST:
                    # the port still works, but nothing answers
                    self._lost(f"no answer from the actuator on {self._port} "
                               f"(wires loose, UNO Q off or bridge stopped?)")
                    return
                continue
            self._misses = 0
            if not reply.get("ok"):
                log(f"refused {msg}: {reply.get('error')}")

    def _lost(self, why: str) -> None:
        log(f"connection lost: {why}. Searching for the actuator again")
        try:
            self._ser.close()
        except OSError:
            pass
        self._ser = self._port = None

    def _exchange(self, msg: dict, timeout: float) -> dict | None:
        """Send one message, return the reply with the same id (None on timeout).
        Lines that are not that reply (debug prints, late replies) are skipped."""
        self._next_id += 1
        msg = {"id": self._next_id, **msg}
        self._ser.write((json.dumps(msg) + "\n").encode())
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self._buf += self._ser.read(self._ser.in_waiting or 1)
            while b"\n" in self._buf:
                line, self._buf = self._buf.split(b"\n", 1)
                try:
                    reply = json.loads(line)
                except ValueError:
                    continue
                if isinstance(reply, dict) and reply.get("id") == msg["id"]:
                    return reply
        return None
