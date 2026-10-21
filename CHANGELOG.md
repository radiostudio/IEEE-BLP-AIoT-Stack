# Changelog

## v0.1.0 (2026-10-21)

### Fixed
- **PIR `event_count` inconsistent on the dashboard.** The count restarted at 0
  on every node reboot and a PIR already high at power-up reported `motion=1`
  with `event_count=0`. The gateway now keeps the count rising across node
  reboots and uint16 wraps, and counts the boot-time high as one event.
  - New `gateway/decoder/counters.py` (`CounterTracker`), applied in
    `gateway/pipeline.py` before readings are stored and rules evaluated.
  - Opt-in per measurand from the card: `gateway/cards/03_pir.json` gets
    `"counter": {"scope": "since_boot", "level_field": "motion"}`.
  - A reboot is a `tick_ms` drop of more than 10 s; a smaller regression is a
    stale, out-of-order frame and does not move the state.
  - State is in memory: after a gateway restart the series re-baselines at the
    node's current raw count.
- **Low delivery ratio on the Uno Q (about 20% for a 2 s node).** Not radio
  loss. bleak's passive scan was rejected (no `or_patterns`, and BlueZ
  experimental interfaces were off), so the gateway silently fell back to an
  active scan whose duplicate filter delivered about one frame per 10.5 s per
  node.
  - `gateway/scanner/ble_scan.py` now passes `or_patterns` for passive
    scanning on Linux and logs `BLE scan mode: passive` or
    `active (passive unavailable: ...)` instead of falling back silently.
    Other platforms are unchanged.
  - Requires `Experimental = true` in `/etc/bluetooth/main.conf` on the board
    (set on the Uno Q on 2026-10-08).
  - Measured on the Uno Q after the change: 100% of `seq` values captured for
    10 of 11 nodes (BME688 96%) over 60 s.

### Added
- **Relay actuator card (type 18, provisional)** for the new
  `IEEE-BLP-RelayActuator` node, which scans for a CONTRACT command frame and
  latches a relay with a beep indication. `gateway/cards/18_relay_actuator.json`
  (`role: actuator`, no measurands), `build_relay_command()` in `core.py`,
  `python -m gateway relay on|off` (prints the bytes to advertise from nRF
  Connect; the gateway cannot transmit yet), and
  `gateway/tests/test_relay_command.py`. The rule engine's `gpio` action is
  still a stub and does not send this frame.
- `gateway/tests/test_counters.py`: 6 checks for the counter tracker
  (reboot, boot-high, idle node, no double count with fixed firmware, uint16
  wrap, stale frame). Run: `python -m gateway.tests.test_counters`.
- `FIX_PIR_EVENT_COUNT_2026-10-07.md`: write-up of the PIR fix and its
  validation.

### Documentation
- `gateway/README.md` (Uno Q porting, step 2): replaced "the code falls back to
  active scanning by itself" with the `Experimental = true` setup, how to
  verify it from the log, and what a low delivery ratio then means.
- `00_ARCHITECTURE_AND_CODE_STRUCTURE.md`: `ble_scan.py` entry notes the Linux
  prerequisite.
- `FIX_BLE_DELIVERY_RATIO_2026-10-08.md`: measurements and cause.

### Notes
- Receiving every frame raises the stored row rate to roughly 890,000 rows per
  day (about 80 MB/day) on the Uno Q. `python -m gateway downsample` rolls raw
  rows older than 7 days into aggregates but is not scheduled.
- The matching node-side fix is in the IEEE-BLP-MotionSensor repo (count a
  high boot level as one event). The gateway fix works without it.
- Not yet validated on hardware: the boot-high path with a real PIR that is
  high at power-up.
