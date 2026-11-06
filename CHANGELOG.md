# Changelog

## Unreleased

### Added
- **InfluxDB 1.x storage backend (hybrid), now the default.** Readings and
  annotations go to InfluxDB (database `aiot_blp`); sensor inventory and
  experiments stay in SQLite, in `gateway/data/gateway_meta.db`. Raw readings
  are kept for a configurable retention (default `7d`) and rolled up by an
  InfluxDB continuous query into configurable buckets (default `5m`,
  mean/min/max/count) kept for a configurable time (default `52w`); queries
  older than the raw retention read the rollups. Standard library only.
  `gateway/store/influx.py`, `gateway/store/__init__.py` (`open_store`).
- `migrate-sqlite` command: copies an existing SQLite `gateway.db` into
  InfluxDB and `gateway_meta.db`; `--dry-run`; safe to re-run.
  `gateway/store/migrate.py`.
- `smoke --backend influx`: the self-test against the configured InfluxDB, in
  a throwaway database.
- **Docker stack for the Uno Q / Linux:** `Dockerfile`, `compose.yaml`
  (`influxdb:1.13.1`, `gateway` on 8931, `mcp` on 8000),
  `docker/entrypoint.sh`, `.dockerignore`, `.env.example`. Built on the board.
  Bluetooth through the host D-Bus socket. See `gateway/README.md`, "Docker".
- Environment variables override `config.json` in memory (`GATEWAY_*`,
  `INFLUX_*`); the effective store is printed at startup.
- **Dashboard: Live and History tabs.** Live keeps the sensor table (the
  journal list under it is removed); it now updates values in place instead
  of rebuilding the table every 5 s. History has 1 h / 12 h / 24 h / 7 d
  windows with the point spacing scaled to the window (10 s to 30 min) and
  one grid of charts in sensor order; each card shows its sensor's status,
  part and delivery, plus units, axes, mean/min/max, a min/max band, journal
  notes on the timeline, offline gaps and a hover readout. Sensor filter and
  full-width expand.
- Dashboard API: `/api/card/<uid>` (part and units), `agg=band` on
  `/api/series` (mean, min and max per bucket in one request), `?since=` on
  `/api/annotations`. `agg="band"` works on both store backends.
- **Grafana in the Docker stack:** `grafana` service (`grafana/grafana:13.2.5`,
  port 3000, volume `grafana-data`) wired to the stack's InfluxDB. Viewers
  need no login; admin password from `GRAFANA_ADMIN_PASSWORD` (default
  `radiostudio`). Provisioned from `docker/grafana/`: the InfluxDB data source
  and a locked "AIoT sensors" dashboard (Source raw/rollup, Sensor and Field
  dropdowns, one chart per field, journal notes as markers, last frame per
  sensor). See `gateway/README.md`, "Grafana".
- **Analysis libraries in the Docker image:** pandas, polars, pyarrow, cbor2,
  matplotlib (`MPLBACKEND=Agg`), plotly, `influxdb` and `influxdb-client`,
  listed in `gateway/requirements-docker.txt`. The native setup is unchanged.
- **Device ID: devices that share a sensor ID are kept apart.** Two nodes of
  one type with the same kit ID (both `1:1`) used to be merged into one
  sensor, and one dropped the other's frames as duplicates. The gateway now
  keeps the sender's Bluetooth MAC (`RawFrame.mac`) and keys dedupe, counter
  tracking and time reconciliation on sensor ID + MAC. The sensor ID itself is
  unchanged.
  - Stored as column `mac` in the SQLite `sensors` (key now `uid, mac`),
    `readings` and `aggregates` tables, and as tag `mac` in InfluxDB.
  - Dashboard: **Device ID** column after Part on Live, one row per device;
    one History card per device. `/api/latest` and `/api/series` take
    `?mac=`; `/api/sensors` lists one entry per device.
  - `simulate --twin <type_id>`: a second simulated device of that type.
  - `gateway/tests/test_multi_device.py` (SQLite; `influx` argument adds
    InfluxDB).
- **Device ID, part 2: tools, agents, rules and Grafana per device.**
  - MCP tools `read_latest`, `query_timeseries`, `validate_reading` take an
    optional `mac`. Without it: one device answers as before plus `mac`;
    several answer per device under `devices`; none gives the usual "no
    readings". A given value is still judged from the card alone.
    `gateway/mcp_server/tools/devices.py`. CLI: `tool ... --mac`.
  - Recipe evidence packs: one entry per device (`1:2@<mac>.<field>`) with a
    caveat; liveness notes name the MAC.
  - Rules: optional `"mac"` per condition (checked by `deploy_rule`). The
    engine keeps values and timers per device; without `mac` a condition
    holds if any device meets it, so a faulty device no longer resets a
    healthy one's timer.
  - Grafana: Device dropdown, per-device lines, Device ID column in "Last
    frame per device".

### Changed
- `compose.yaml`: container logs are capped at 3 files of 10 MB per service
  (json-file `max-size`/`max-file`); Docker kept every line before.
- `compose.yaml`: only the `gateway` service builds the image; `mcp` reuses
  it (`pull_policy: never`). Each `--build` used to build it twice and leave
  an extra `<none>` image behind.
- **Databases from before the Device ID change are refused** at startup with
  "old database format"; there is no migration. Back up and reset them, see
  `gateway/README.md`, "Reset the data". `migrate-sqlite` still reads an old
  `gateway.db` (its sensors get an empty Device ID).
- **Default `store_backend` is `influx`.** A native run without InfluxDB stops
  with "InfluxDB not reachable"; set `"store_backend": "sqlite"` in
  `gateway/config.json` for the previous behaviour, which is unchanged.
  `smoke` still defaults to SQLite, so the onboarding scripts are unaffected.
- `downsample` does nothing on the InfluxDB backend (InfluxDB rolls up itself).
- `run` and `simulate` flush queued writes on Ctrl+C and on SIGTERM
  (`docker stop`).

## v0.1.1 (2026-10-26)

### Changed
- **PIR `event_count` now restarts at 0 when the node reboots**, so the
  dashboard follows the node instead of carrying the pre-reboot total. This
  reverses the v0.1.0 behaviour ("keeps rising across node reboots"). uint16
  wraps within one boot are still carried forward, and a PIR high at power-up
  still counts as one event. `gateway/decoder/counters.py`,
  `gateway/tests/test_counters.py` (`test_reboot_resets_count`).
- **SCT-013 card (type 11): `irms_a` renamed to `load_current_rms_a`, and
  `apparent_va` dropped.** The card, its plausibility key, the `cold_chain`
  recipe, the dashboard decimal setting (3 places) and the workshop example
  query use the new name. Existing stored rows under `irms_a` are not
  renamed, so queries for the old field find nothing on a database that
  predates this change.
  - `firmware/sim-firmware/README.md` still lists `irms_a` and `va` for type 11;
    not updated here.

### Added
- `tools/gateway_loadtest.py`: stdlib load test that simulates N phones opening
  the dashboard (`dashboard` and `ping` modes) and reports per-endpoint
  latency, errors and a SMOOTH / DEGRADED / OVERLOADED verdict.
- `todo.md`: checklist of packages and system setup for a gateway transmit
  path on the Windows PC and the Uno Q (relay actuator). Nothing in it has
  been installed or tried.
- `currentstatus.md`: status of the stack software.

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
