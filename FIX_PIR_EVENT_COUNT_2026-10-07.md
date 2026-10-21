# PIR event_count fix: gateway and firmware (2026-10-07)

## Problem

On the dashboard the PIR (`1:3`) sometimes showed `motion=1` with `event_count=0`,
and the count went backwards.

Evidence from the gateway DB on the UNO Q (253 stored PIR frames, 10:40-14:04):

| Time | seq | motion | event_count |
|---|---|---|---|
| 13:29:55 | 27829 | 1 | 2 |
| 13:30:06 | 27813 | 1 | **0** |
| 13:30:16 | 27818 | 1 | **0** |
| 13:30:48 | 27834 | 1 | 3 |

The count dropped 2 -> 0 and `seq` stepped back by 16, which is a node reboot.
`SeqStore` persists `seq` but loses the last unsaved increments on reboot. Away
from that reboot, every real rising edge incremented the count; there was no
other inconsistency.

## Root causes

1. **Firmware.** At init the node seeds `level` from the pin but never counts it.
   The ISR counts rising edges only (`lvl && !level`). A PIR that is already high
   at power-up (the AS312 is, while it warms up) therefore reports `motion=1`,
   `count=0` until the next real edge.
2. **Firmware.** The count is RAM-only, so it restarts at 0 on every reboot
   (inherent to "since boot"; the card says so).
3. **Gateway.** Nothing handled that reset. `registry.py` stores the raw value,
   so the dashboard shows a count that goes backwards after a reboot.

Decode and scaling were checked and are correct. This is not a decoder bug.

## Changes

### Gateway (`IEEE-BLP-AIoT-Stack/gateway`)

| File | Change |
|---|---|
| `decoder/counters.py` (new) | `CounterTracker`: turns a since-boot counter into a series that keeps rising across node reboots and uint16 wraps |
| `pipeline.py` | Runs decoded values through `CounterTracker` before the store and the rule engine |
| `cards/03_pir.json` | `event_count` gets `"counter": {"scope": "since_boot", "level_field": "motion"}`, so behaviour is card-driven, with no per-sensor code in the pipeline |
| `tests/test_counters.py` (new) | 6 unit tests, see below |

Behaviour:
- **Reboot:** detected when `tick_ms` drops by more than 10 s. What was counted so far is carried into an offset.
- **Stale frame:** a smaller `tick_ms` regression is treated as a late, out-of-order frame. It is reported but does not move state.
- **Wrap:** a count drop within one boot adds 65536.
- **Boot-high bias:** if the first frame of a boot shows `motion=1` and raw count 0, one event is added for that boot. Firmware that already counts boot-high reports `count=1`, so it is not double-counted.
- **Limitation:** state is in memory. After a gateway restart the series starts again from the node's current raw count.

### Firmware (`IEEE-AIoT-Sensors/IEEE-BLP-MotionSensor`)

| File | Change |
|---|---|
| `Modules/Src/MotionSensor.c` | In `MotionSensor_Init`, seed `m_MotionLevel` and set `m_MotionCount = m_MotionLevel` under the lock, **before** `gpio_isr_handler_add`. A PIR high at boot now counts as one event. Seeding before the handler is attached also closes a small race where an edge could land between the seed and the ISR |
| `Modules/Inc/MotionSensor.h` | Contract comment updated: `motion=1` implies `event_count >= 1` |

The same pattern exists in `sim-firmware/src/interfaces/gpio_event.cpp` (the
simulator's shared driver). It was **not** changed; it is not what the real PIR
node runs.

## Validation done

| Check | Result |
|---|---|
| `python -m gateway.tests.test_counters` on the PC | 6/6 pass |
| `python -m gateway smoke` on the PC (full pipeline, 14 simulated types) | passed |
| `python -m gateway.tests.test_counters` on the UNO Q, using the board's own venv python | 6/6 pass |
| Firmware build, ESP-IDF 5.4 (`idf.py build`, esp32) | 1324/1324, image created, 32% of the app partition free |
| Firmware flash to the PIR node (COM7), `esptool write_flash` | written, hash verified |
| Live: PIR node advertising after flash; gateway stored its frames | seq 29057 `motion=0, count=0`, then seq 29058 `count=1`; dashboard `/api/latest/1:3` and `/api/sensors` returned the PIR row, `delivery_ratio` 1.0 |

The 6 unit tests:
`reboot_keeps_count_rising` (replays the real 13:29-13:30 sequence),
`motion_high_implies_count_at_least_one`, `idle_node_stays_zero`,
`firmware_that_counts_boot_level_is_not_double_counted`, `uint16_wrap`,
`stale_frame_is_not_a_reboot`.

## Not validated

- **Boot-high on real hardware.** The PIR was low at boot after the flash, so the new firmware path (counting a high boot level) has not run on hardware. The `count=1` seen live came from a real edge between two frames.
- **Gateway-side boot-high bias** was exercised only by unit tests, not by a live frame.
- **Gateway restart behaviour** (re-baselining at the node's raw count) is documented but not tested.
- The smoke test was run on the PC only, not on the board.
- No firmware unit tests exist in the motion sensor repo; its only check was the build plus live behaviour.

## Deployment notes (UNO Q)

- Live gateway tree: `/home/arduino/IEEE-BLP-AIoT-Stack/gateway`. Files pushed over adb (CRLF kept): `decoder/counters.py`, `tests/test_counters.py`, `pipeline.py`, `cards/03_pir.json`.
- The DB was backed up and then reset. Backup: `/home/arduino/db-backups/gateway-20261007-141620/`. It was verified before the live DB was removed (integrity ok, 563,121 readings, 12 sensors).
- Both services (`IEEE-aiot-BLE-daemon`, `IEEE-aiot-MCP-daemon`) were restarted by stopping the processes. systemd restarted them with `Restart=always` (sudo needs a password, so `systemctl` was not used).
- Firmware flashed without erasing flash, so the persisted `seq` was kept. The adapter's RTS is not wired to EN, so the node needed a manual boot-mode exit and power-cycle.

## Follow-ups

- Commit both repos (nothing is committed yet).
- Copy the DB backup to the PC.
- Power up the remaining nodes and re-check the dashboard.
- Power-cycle the PIR with the sensor in view of motion and confirm the boot-high case on hardware (expect first frame `motion=1, count=1`).
- Apply the same boot-high fix to `sim-firmware/src/interfaces/gpio_event.cpp` if the simulator should match.
