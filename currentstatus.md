# Current Status

Status of the AIoT stack software (gateway, sensor cards, dashboard, MCP server, onboarding scripts) as of 2026-10-21, on branch `feature/onboarding-scripts`. Intended first release: `v0.1.0`.

How to read this: **Verified** means run and passed in this repo's own tests or confirmed on hardware per the repo's write-ups. **Not verified** means the code exists but has not been shown working end to end. Anything not listed here has not been assessed.

---

## Summary

| Area | State |
|---|---|
| BLE scan, decode, store, rules, MCP tools | Working. Smoke test passes. |
| Sensor cards | 17 sensor cards (types 1-17) plus 1 provisional actuator card (type 18) |
| Dashboard | Working, served on the network on port 8931 with live history charts |
| Onboarding scripts (Windows and Linux/macOS) | Working per the recorded fresh-Windows test |
| Actuation (relay) | Partial. The gateway can build the command frame but cannot transmit it. |
| Docker image | Not in this repo. See "Release and Docker" below. |

---

## Gateway

Entry point: `python -m gateway run` (or `gateway.bat` / `gateway.sh`, which pick the right Python). Config is `gateway/config.json` (dashboard port 8931, SQLite store at `gateway/data/gateway.db`, downsample period 300 s).

| Component | Path | Notes |
|---|---|---|
| Scanner | `gateway/scanner/` | `ble_scan.py` (bleak), `sim_source.py` (simulated source), `dedupe.py` |
| Decoder and registry | `gateway/decoder/`, `gateway/core.py` | Loads cards, decodes CONTRACT frames. `reconcile.py` handles the tick clock. `counters.py` keeps counters rising across node reboots. |
| Pipeline | `gateway/pipeline.py` | Decode, counter tracking, store, rule evaluation |
| Store | `gateway/store/` | SQLite, plus `downsample.py` |
| Rules | `gateway/rules/` | Engine plus approved rules in `rules.d/` (one: `corridor_lighting.json`) |
| MCP server | `gateway/mcp_server/` | Tools: `list_sensors`, `describe_sensor`, `read_latest`, `query_timeseries`, `validate_reading`, `annotate`, `capture_experiment`, `deploy_rule` |
| Agents | `gateway/agents/` | Orchestrator and two recipes: `cold_chain`, `occupancy` |
| Dashboard | `gateway/dashboard/` | Live table plus history charts, window selectable |

### Tests (run on 2026-10-21 with `.venv-gateway`)

| Test | Result |
|---|---|
| `python -m gateway.tests.smoke_test` | Passed: scanner, decode, store, tools and rules healthy |
| `python -m gateway.tests.test_counters` | Passed |
| `python -m gateway.tests.test_relay_command` | Passed |

The smoke test uses simulated data, not radio.

---

## Sensor cards (`gateway/cards/`)

| Type | Card | Measurands |
|---|---|---|
| 1 | DS18B20 | temperature_c |
| 2 | BME688 | temperature_c, humidity_pct, pressure_hpa, iaq, eco2_ppm, bvoc_ppm |
| 3 | PIR (AS312 class) | motion, event_count |
| 4 | 4-20 mA transmitter (anemometer example) | loop_ma, wind_ms |
| 5 | RS485 energy meter | voltage_v, power_w, energy_kwh |
| 6 | SCD41 | co2_ppm, temperature_c, humidity_pct |
| 7 | VEML7700 | lux |
| 8 | MEMS mic SPL | spl_db |
| 9 | JSN-SR04T | distance_mm |
| 10 | Reed switch | door_open, transition_count |
| 11 | SCT-013-030 | load_current_rms_a |
| 12 | SEN0193 soil moisture | raw_mv, moisture_pct |
| 13 | Bare-trace water presence | wet, raw_mv |
| 14 | AT42QT1010 touch | present, touch_count |
| 15 | RS485 soil probe | moisture_pct, soil_temp_c |
| 16 | STPM32 energy meter | voltage_v, current_a, power_w |
| 17 | SHT40 | temperature_c, humidity_pct |
| 18 | Relay and buzzer actuator (provisional) | none (`role: actuator`) |

Counter-type measurands (`event_count` on PIR, `transition_count` on reed) carry a `counter` annotation (`scope: since_boot`, `level_field`). The gateway uses it to keep the count rising across node reboots and uint16 wraps. Only PIR has the fix exercised by a test; the reed annotation was added in `e26b7a4` and has no dedicated test.

---

## What changed recently (see `CHANGELOG.md`)

- PIR `event_count` now rises across node reboots and wraps (`gateway/decoder/counters.py`).
- Passive BLE scan with `or_patterns` on Linux, which raised capture on the Uno Q to 100% of `seq` values for 10 of 11 nodes over 60 s. Requires `Experimental = true` in `/etc/bluetooth/main.conf`.
- Dashboard served over the network with live history charts.
- Relay actuator card (type 18) and `build_relay_command()`.
- Reed `transition_count` marked as a since-boot counter.

---

## Known gaps and open items

**Actuation (open, tracked in `todo.md`)**
- The gateway cannot transmit. `python -m gateway relay on|off` only prints the bytes to advertise from another tool. The rule engine's `gpio` action is a stub.
- The registry ignores `role: actuator`, so `describe_sensor` and `validate_reading` treat card 18 as a sensor with no measurands.
- Command frames are not yet defined in `00_ARCHITECTURE_AND_CODE_STRUCTURE.md`. Open decisions: type ID range, indication contract, authentication, acknowledgement, sequence rule, transmit path.
- The command channel is unauthenticated. Do not drive a load whose unintended switching is dangerous.

**Data and storage**
- Receiving every frame gives roughly 890,000 rows per day (about 80 MB/day) on the Uno Q. `python -m gateway downsample` is not scheduled.
- Counter state is in memory. After a gateway restart a counter series re-baselines at the node's current raw count.

**Not verified**
- PIR boot-high path with a real PIR that is high at power-up.
- Reed counter annotation on hardware.

**Hardware observations from the bench (not software defects, not triaged)**
- STPM32 current and voltage history looked noisy on the dashboard (seen in bench photos). Cause not established, and no fix is in this release.
- A DS18B20 history chart showed a maximum of 327.67, which is likely a bad value.

---

## Platforms

| Platform | State |
|---|---|
| Windows PC | Gateway runs with `gateway.bat`. Bluetooth must be switched on. |
| Arduino Uno Q (Linux) | Runs the gateway. Needs BlueZ `Experimental = true` for passive scan. See `gateway/README.md`. |
| Linux / macOS | Onboarding via `setup.sh` and `bootstrap.sh`. Not re-tested for this status. |

Onboarding: `bootstrap.ps1` / `bootstrap.sh` fetch the code and run `setup`. A fresh-Windows ZIP-bootstrap test is recorded in the repo history (`51c4798`).

---

## Not in this repository

- **Sensor firmware** for individual nodes (for example `IEEE-BLP-LUX-SENSOR`, the SCD41/CO2 firmware, `IEEE-BLP-RelayActuator`) lives in separate repos. `firmware/` here holds only `sim-firmware` and `rehearsal_advertiser`.
- **Docker packaging.** There is no Dockerfile or compose file here.

---

## Release and Docker

- No git tags or GitHub Releases exist yet. The plan is to merge this branch to `main` and tag `v0.1.0`.
- The Docker build should fetch the tag, not a branch or commit:
  `git clone --branch v0.1.0 --depth 1 <repo-url>`, or a build arg with the tag as its default.
- Before tagging: rename the "Unreleased" heading in `CHANGELOG.md` to `v0.1.0` with the release date.
