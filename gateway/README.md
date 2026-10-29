# AIoT Gateway

Reference implementation of the gateway contract from
`../00_ARCHITECTURE_AND_CODE_STRUCTURE.md` Section 7: BLE scan in, card-driven
decode, SQLite timeseries store, MCP endpoint out, deterministic edge rules,
cloud-loop agent orchestration.

## Storage backend

`store_backend` in `config.json` picks where data goes. The default is
`influx`, for the Uno Q Docker stack (see "Docker (Uno Q / Linux)" below):

| Backend | Where data goes |
|---|---|
| `influx` (default) | Hybrid: readings and annotations in InfluxDB 1.x (database `aiot_blp`); sensor inventory and experiments in `gateway/data/gateway_meta.db` |
| `sqlite` | Everything in `gateway/data/gateway.db`, as before |

**Running natively on a laptop without InfluxDB:** set
`"store_backend": "sqlite"` in `gateway/config.json`, or the gateway stops at
startup with "InfluxDB not reachable". `smoke` always uses SQLite unless
given `--backend influx`.

With InfluxDB, raw readings are kept for `influx.raw_retention` (default
`7d`) and rolled up by InfluxDB itself into `influx.rollup_period` buckets
(default `5m`, mean/min/max/count) kept for `influx.rollup_retention`
(default `52w`). Queries older than the raw retention are served from the
rollups, so history does not stop at the raw retention. The gateway applies
these settings at every start: shortening a retention deletes the data older
than the new limit. `downsample` is not needed with InfluxDB.

Environment variables override `config.json` in memory (the file is never
rewritten): `GATEWAY_STORE_BACKEND`, `GATEWAY_KIT_ID`, `GATEWAY_BLE_ADAPTER`,
`GATEWAY_RULES_DIR`, `INFLUX_URL`, `INFLUX_DB`, `INFLUX_USER`,
`INFLUX_PASSWORD`, `INFLUX_RAW_RETENTION`, `INFLUX_ROLLUP_PERIOD`,
`INFLUX_ROLLUP_RETENTION`, `INFLUX_META_DB_PATH`. The effective store is
printed at startup:

```
[gateway] store: influx (aiot_blp @ http://influxdb:8086), raw kept 7d, rollup 5m kept 52w; inventory in /app/gateway/data/gateway_meta.db
```

## Quick start (no hardware needed)

Recommended: from the `ai_first_course/` directory, run the one-command setup
(creates the environment, installs dependencies, runs the self-test):

```
python3 start_installation.py     # macOS/Linux
python start_installation.py      # Windows
```

Afterwards, run any gateway command through `gateway.sh` / `gateway.bat` -
no manual environment activation needed:

```
bash gateway.sh simulate    # macOS/Linux - 14 simulated SIMs + dashboard on :8080
gateway.bat simulate        # Windows
```

Manual setup (also useful for porting to other hardware, see below): from
the `ai_first_course/` directory:

```
python -m gateway smoke        # end-to-end self-test
python -m gateway simulate     # 14 simulated SIMs + dashboard on :8080
```

With hardware, Bluetooth turned on on your laptop, and `pip install bleak`:

```
python -m gateway run          # live BLE scan + dashboard
```

If Bluetooth is off, `run` starts and the dashboard still comes up, but no
sensors will ever show up as online - turn Bluetooth on (in your OS's
system settings, not something this gateway can do for you) and it starts
picking them up.

MCP for Claude (`pip install mcp`), then in Claude Desktop / Claude Code:

```
python -m gateway mcp          # stdio transport
```

## Command reference

| Command | Purpose |
|---|---|
| `run` | live BLE scan into the store, rules evaluated, dashboard served |
| `simulate [--fault 1:stuck]` | same pipeline on simulated SIMs; fault injection for the validation labs |
| `mcp` | MCP server: 10 tools, card resources, experiment prompt templates |
| `dashboard` | thin local view only |
| `recipe occupancy` | cloud-loop fusion recipe -> evidence pack (+model answer if ANTHROPIC_API_KEY set) |
| `liveness` | watchdog pass: flags silent sensors into the journal |
| `approve-rule <name>` | human approval step for agent-authored rules |
| `token` | prints the deploy_rule capability token to hand to an agent |
| `downsample` | roll old raw rows into aggregates (eMMC-friendly); SQLite backend only |
| `smoke [--backend influx]` | self-test of the whole pipeline; `--backend influx` runs it against the configured InfluxDB in a throwaway database |
| `migrate-sqlite [--source PATH] [--dry-run]` | copy an existing SQLite `gateway.db` into InfluxDB + `gateway_meta.db`; safe to re-run |
| `relay on\|off [--seq N]` | prints the type-18 relay command frame to advertise from nRF Connect (the scanner is receive-only) |

## Layout (mirrors the architecture document)

```
gateway/
├── core.py                BLE payload spec (the one place the frame layout lives)
├── pipeline.py            scan -> dedupe -> decode -> reconcile -> store -> rules
├── scanner/   ble_scan.py (bleak), dedupe.py, sim_source.py (14-SIM simulator)
├── decoder/   registry.py (cards -> parsers), reconcile.py (seq loss, tick alignment)
├── store/     db.py (SQLite WAL), influx.py (InfluxDB hybrid), migrate.py, downsample.py
├── cards/     14 sensor cards (JSON), the machine-readable contracts
├── mcp_server/ server.py + tools/ (8 tools), prompts/, resources/
├── rules/     engine.py (deterministic, no LLM), rules.d/ (approved + .pending)
├── agents/    orchestrator.py (recipes, watchdog), recipes/
├── dashboard/ stdlib HTTP + one page, localhost only
└── tests/     smoke_test.py
```

## Porting to Raspberry Pi / Arduino Uno Q

The code is identical on all targets; porting is environment work:

1. **Python 3.10+** on the target (Raspberry Pi OS and the Uno Q Debian side
   both ship it). Copy the `gateway/` directory, `pip install -r
   gateway/requirements.txt`.
2. **BLE backend:** bleak uses BlueZ on Linux automatically. Give the user
   bluetooth permissions or run with the `bluetooth` group.

   **On the Uno Q, enable BlueZ experimental mode, or the gateway will hear
   only about one frame in five.** Passive scanning needs it. Without it the
   gateway falls back to an active scan, and BlueZ's active scan filters
   repeated advertisements: each node is heard about once every ~10.5 s no
   matter how fast it transmits, so the delivery ratio reads about
   `sample period / 10.5 s` (around 20% for a 2 s node) even though nothing is
   being lost over the air. Enable it once per board (needs sudo):

   ```
   sudo cp /etc/bluetooth/main.conf /etc/bluetooth/main.conf.bak
   sudo sed -i 's/^#Experimental = false/Experimental = true/' /etc/bluetooth/main.conf
   sudo systemctl restart bluetooth      # then restart the gateway
   ```

   Check the gateway log for `BLE scan mode: passive`. If it says
   `BLE scan mode: active (passive unavailable: ...)`, the flag is missing or
   the BlueZ is older than 5.56 / the kernel older than 5.10. Measured on an
   Uno Q (BlueZ 5.82, kernel 6.16) with 11 nodes: active scan about 12-75%
   of `seq` values per node, passive scan 100% (BME688 96%). To undo, restore
   the `.bak` copy and restart Bluetooth. The delivery ratio on the dashboard
   is cumulative, so it recovers slowly after the fix unless the database is
   reset.
3. **GPIO actions:** `rules/engine.py` has a clearly marked stub for the
   `gpio` action type; map it to gpiozero or libgpiod on the target. Rule
   specs do not change.
4. **Storage:** with the InfluxDB backend (default, and the Docker stack)
   nothing to schedule: retention and rollups run inside InfluxDB. With the
   SQLite backend, keep the WAL store on eMMC but schedule
   `python -m gateway downsample` daily (cron) to bound writes; on a Pi with
   an SD card do the same.
5. **Service:** run `python -m gateway run` under systemd; run `mcp` on
   demand or expose it via an SSE transport if the cloud loop connects
   remotely.

Nothing in the pipeline imports Windows-only or Linux-only modules; the smoke
test is the porting acceptance test: if `python -m gateway smoke` passes on
the target, the gateway works there.

## Docker (Uno Q / Linux)

`compose.yaml` at the repository root runs the gateway as three containers,
built on the board itself (the Uno Q is `linux/arm64`), plus Grafana:

| Service | What it runs | Port |
|---|---|---|
| `influxdb` | `influxdb:1.13.1`, data in the `influxdb-data` volume | none published: only the gateway containers reach it |
| `gateway` | `run`: BLE scan, rules, dashboard | `8931` |
| `mcp` | `mcp`: MCP server (streamable HTTP, path `/mcp`) | `8000` |
| `grafana` | `grafana/grafana:13.2.5`, reads InfluxDB; see "Grafana" below | `3000` |

**Linux only.** The `gateway` container uses the host's BlueZ through the
mounted D-Bus socket. Docker Desktop on Windows and macOS runs containers in a
VM with no access to the laptop's Bluetooth.

### First start on the Uno Q

1. Docker with the Compose plugin: `docker compose version` must work.
2. BlueZ experimental mode on the host (step 2 of "Porting" above). The
   container cannot change host Bluetooth settings.
3. Stop any InfluxDB installed directly on the board; the stack brings its
   own: `sudo systemctl disable --now influxdb`.
4. From the repository root:

   ```
   cp .env.example .env              # once; settings live in .env
   docker compose up -d --build
   docker compose logs -f gateway
   ```

   Expect `[gateway] store: influx (aiot_blp @ http://influxdb:8086) ...`,
   then `BLE scan mode: passive` and sensors coming online.
5. Dashboard: `http://<uno-q-address>:8931/`. MCP clients:
   `http://<uno-q-address>:8000/mcp`. Grafana: `http://<uno-q-address>:3000/`.
6. Acceptance test against the real InfluxDB (uses a throwaway database):
   `docker compose run --rm gateway smoke --backend influx`

### Where things live

| What | Where on the Uno Q |
|---|---|
| Readings, annotations, rollups | InfluxDB, Docker volume `aiot-blp_influxdb-data` |
| Grafana users, settings, dashboards saved with "Save as" | Docker volume `aiot-blp_grafana-data` |
| Sensor inventory, experiments | `gateway/data/gateway_meta.db` (repository folder) |
| SQLite backend database (if `GATEWAY_STORE_BACKEND=sqlite`) | `gateway/data/gateway.db`, the same file a native run uses |
| Approved rules, capability token | `gateway/data/rules.d/`, `gateway/data/.capability_token` (shipped rules are copied in on first start) |

Files in `gateway/data/` are created by the container as root; use `sudo` to
delete them. `docker compose down` keeps all data; `docker compose down -v`
also deletes the InfluxDB and Grafana volumes.

### Grafana

`http://<uno-q-address>:3000/` opens the **AIoT sensors** dashboard. No
login is needed to view it; the admin login (user `admin`) is for changing
Grafana itself.

- **Admin password:** `GRAFANA_ADMIN_PASSWORD` in `.env`, default
  `radiostudio`. The default is public in this repository, so change it before
  the first start if the board is on a shared network. Grafana reads it only
  on its first start; later changes need
  `docker compose exec grafana grafana cli admin reset-admin-password <new>`.
- **Dashboard:** one chart per field, one line per sensor (mean per
  interval), journal notes as orange markers, and a "Last frame per sensor"
  table. Dropdowns:
  - **Source**: `raw` (every frame, kept for `INFLUX_RAW_RETENTION`) or
    `rollup` (mean per `INFLUX_ROLLUP_PERIOD`, kept for
    `INFLUX_ROLLUP_RETENTION`). Use `rollup` for time ranges older than the
    raw retention.
  - **Sensor** and **Field**: filter the charts.
- **Locked:** the dashboard and the InfluxDB data source come from
  `docker/grafana/` in this repository and cannot be saved over in Grafana.
  To experiment, log in as admin and use **Save as**; the copy lives in the
  `grafana-data` volume. To change the shipped dashboard, edit
  `docker/grafana/dashboards/aiot_sensors.json` (Grafana reloads it within
  about 10 s).
- Units, sensor health and delivery ratio are not in InfluxDB; they stay on
  the gateway dashboard (port 8931).

### Analysis libraries in the image

The image also has pandas, polars, cbor2, matplotlib, plotly, `influxdb`
(InfluxQL client) and `influxdb-client`
(`gateway/requirements-docker.txt`). The gateway does not use them; they are
for your own scripts. Put a script in `gateway/data/` (mounted into the
container) and run it:

```
docker compose exec gateway python /app/gateway/data/my_script.py
```

- InfluxDB is at `http://influxdb:8086`, database `aiot_blp`, from inside
  the container.
- matplotlib uses the `Agg` backend (no screen): save figures with
  `savefig()` into `/app/gateway/data/`.
- plotly writes HTML with `write_html()`; PNG export needs `kaleido`, which is
  not installed.
- `influxdb-client` talks to InfluxDB 1.x through its compatibility API:
  writes and InfluxQL work; Flux queries do not (Flux is off in InfluxDB).
- `polars.from_pandas()` needs `pyarrow` (not installed) for text columns;
  build the polars frame from the query rows instead.

### Day-to-day

```
# change a setting: edit .env, then
docker compose up -d

# update the code
git pull && docker compose up -d --build

# approve an agent-authored rule, then reload the rule engine
docker compose exec gateway python -m gateway approve-rule <name>
docker compose restart gateway

# capability token for deploy_rule
docker compose exec gateway python -m gateway token

# look at the data
docker compose exec influxdb influx -database aiot_blp -execute 'SHOW MEASUREMENTS'

# Grafana log (provisioning errors show here)
docker compose logs grafana

# back up InfluxDB (lands in the container; copy it out with docker compose cp)
docker compose exec influxdb influxd backup -portable /var/lib/influxdb/backup
```

### Moving existing SQLite data into InfluxDB

Put the old `gateway.db` in `gateway/data/` (it is already there if the
gateway ran natively on this board), then, before the gateway starts writing
to InfluxDB:

```
docker compose stop gateway mcp
docker compose run --rm gateway migrate-sqlite --dry-run   # counts only
docker compose run --rm gateway migrate-sqlite
docker compose up -d
```

Readings from the last raw retention go to InfluxDB as raw points; all
readings and any `downsample` aggregates also become rollups, so older
history stays queryable. Annotations, sensor counts and experiments are
copied too. `gateway.db` itself is left untouched.

### If Bluetooth does not work in the container

- `BLE scan mode: active (passive unavailable ...)`: BlueZ experimental mode
  is off on the host (step 2 above).
- D-Bus `AccessDenied` / `NotPermitted`: check that `security_opt:
  apparmor:unconfined` is still on the `gateway` service, and that
  `/run/dbus/system_bus_socket` exists on the host.
- No adapter: set `GATEWAY_BLE_ADAPTER=hci0` (see `hciconfig` /
  `bluetoothctl list` on the host) in `.env`.
