# Deploying, testing and maintaining the gateway on the Arduino Uno Q

Branch: `feature/influxdb-docker`, commit `d0524ec` or later. Check with
`git log -1 --oneline`. Since `cea9832` this branch adds:

- **Device ID (MAC)**: two sensor nodes with the same kit ID and type (e.g.
  two DS18B20 boards, both `1:1`) are kept apart by their Bluetooth address.
  Every stored reading carries the MAC; the dashboard has a **Device ID**
  column; Grafana has a **Device** dropdown; MCP tools and rules work per
  device.
- **One image**: `gateway` and `mcp` share one image (`aiot-blp-gateway:local`),
  built once.
- **Log caps**: each container keeps at most 3 log files of 10 MB.

Databases from before the Device ID change are refused with "old database
format". There is no migration: back up and reset them (section
"Reset everything").

Three parts:

1. **Phase 1, Native Python**: the gateway runs from a Python venv and uses
   the InfluxDB 1.13.1 installed on the board.
2. **Phase 2, Docker**: the same gateway, plus InfluxDB and Grafana, runs as
   containers built on the board. "Install Docker" comes first if the
   machine has no Docker yet.
3. **Maintaining the Docker stack**: everything needed day to day once
   Phase 2 runs (status, logs, data, new cards, updates, disk space). Start
   with "Docker in five minutes" if you are new to Docker.

Run every command on the Uno Q (over SSH or its own terminal) from the
repository folder unless a step says otherwise. `<uno-q-ip>` is the board's
IP address on your network (`hostname -I` on the board shows it).

**Other Linux machines (e.g. an Ubuntu PC):** the Docker setup works the
same way. Follow "Before you start", then "Install Docker", then Phase 2;
skip Phase 1, which needs InfluxDB installed on the machine itself. Steps
marked *(Uno Q only)* can be skipped. The images exist for both arm64 (Uno
Q) and amd64 (normal PCs).

**Nothing else is installed by hand.** `docker compose up -d --build` (step
2.5) does it all:

| Part | How it gets onto the machine |
|---|---|
| InfluxDB 1.13.1 | ready-made image `influxdb:1.13.1`, downloaded |
| Grafana 13.2.5 | ready-made image `grafana/grafana:13.2.5`, downloaded |
| Python 3.12 and the libraries (bleak, mcp, pandas, polars, scikit-learn, sktime, JupyterLab, Streamlit, ...) | built into `aiot-blp-gateway:local` by `Dockerfile` from `gateway/requirements-docker.txt` |
| Grafana data source and dashboard | read from `docker/grafana/` in the repository when Grafana starts |
| InfluxDB database, retention policies, rollup | created by the gateway on its first start |

---

## Before you start

| Check | Command | Expected |
|---|---|---|
| OS / CPU | `uname -m` | `aarch64` (Uno Q) or `x86_64` (PC) |
| Python | `python3 --version` | 3.10 or newer (Phase 1 only) |
| Git | `git --version` | any (`sudo apt install -y git` if missing) |
| Bluetooth service | `systemctl is-active bluetooth` | `active` |
| Bluetooth adapter | `bluetoothctl list` | one controller, e.g. `hci0` |
| BlueZ experimental mode | `grep -n '^Experimental' /etc/bluetooth/main.conf` | `Experimental = true` |
| Free disk | `df -h / /home` | a few GB free (see "Disk space") |

If `bluetoothctl` is not found or the service is not active (common on a
fresh Ubuntu server install):

```
sudo apt update
sudo apt install -y bluez
sudo systemctl enable --now bluetooth
```

On a PC, also check that Bluetooth is not switched off (`rfkill list`; if it
says `Soft blocked: yes`, run `sudo rfkill unblock bluetooth`).

If experimental mode is off, turn it on once per machine (from
`gateway/README.md`, "Porting", step 2):

```
sudo cp /etc/bluetooth/main.conf /etc/bluetooth/main.conf.bak
sudo sed -i 's/^#Experimental = false/Experimental = true/' /etc/bluetooth/main.conf
sudo systemctl restart bluetooth
```

---

## Phase 1: Native Python

### 1.1 Get the code

```
git clone --branch feature/influxdb-docker https://github.com/radiostudio/IEEE-BLP-AIoT-Stack.git
cd IEEE-BLP-AIoT-Stack
```

If the repository is already on the board:

```
cd IEEE-BLP-AIoT-Stack
git fetch origin
git switch feature/influxdb-docker
git pull
```

### 1.2 Check the InfluxDB server

```
sudo systemctl enable --now influxdb
systemctl status influxdb --no-pager
curl -si http://localhost:8086/ping | grep -i version
```

Expected: the service is `active (running)` and the header shows
`X-Influxdb-Version: 1.13.1`.

Optional, recommended: keep InfluxDB reachable from the board only. In
`/etc/influxdb/influxdb.conf`, under `[http]`, set:

```
bind-address = "127.0.0.1:8086"
```

Then `sudo systemctl restart influxdb`. The gateway, dashboard and MCP server
stay reachable from the network; only the database port is closed.

You do **not** need to create a database, bucket or retention policy. The
gateway creates the `aiot_blp` database, the `raw` / `rollup` retention
policies and the rollup continuous query on first start.

### 1.3 Set up Python

```
bash setup.sh
```

This creates `.venv-gateway`, installs the packages and runs the SQLite smoke
test. If it adds you to the `bluetooth` group, log out and back in before
step 1.6.

### 1.4 Self-tests

```
bash gateway.sh smoke
bash gateway.sh smoke --backend influx
.venv-gateway/bin/python -m gateway.tests.test_multi_device influx
```

Expected: both smoke tests end with `SMOKE TEST PASSED`. The second line under
the header shows the store, e.g. `store: influx (aiot_blp_smoke_1234 @
http://localhost:8086) ...`. The influx runs use a throwaway database and
drop it at the end. The Device ID test prints one `ok:` line per test and
`ok: influx_two_devices` at the end.

Run `gateway.sh` from the repository root.

### 1.5 Simulated sensors

Use a separate database so simulated data stays out of `aiot_blp`:

```
INFLUX_DB=aiot_blp_sim bash gateway.sh simulate --twin 1
```

`--twin 1` adds a second DS18B20 under `1:1`, so both devices of one sensor
ID can be checked without hardware. Simulated MACs look like
`02:00:00:01:01:01` and `02:00:00:01:01:02`.

Check:

- The log shows `[gateway] store: influx (aiot_blp_sim @ http://localhost:8086) ...`
- On your laptop, `http://<uno-q-ip>:8931/` opens on the **Live** tab with 15
  rows (14 sensors, `1:1` twice with two Device IDs); the values change in
  place every 5 s without the table jumping.
- The **History** tab shows a chart per device and field; the two `1:1`
  cards show `· 02:00:00:01:01:01` and `· 02:00:00:01:01:02`.
- Ctrl+C prints `[gateway] stopped. frames received: ...`

Clean up:

```
influx -execute 'DROP DATABASE aiot_blp_sim'
```

### 1.6 Real sensors over Bluetooth

Power on the ESP32 sensor nodes, then:

```
bash gateway.sh run
```

Check:

- `[gateway] BLE scan mode: passive`
- one `[gateway] <uid> <MAC> (<part>) online: ...` line per node
- the dashboard at `http://<uno-q-ip>:8931/` shows your nodes, with the
  delivery ratio close to 100%

If the gateway stops with "old database format", the files in
`gateway/data/` are from before the Device ID change: back them up and
remove them (see "Reset everything", the native commands).

Leave it running for the next steps.

### 1.7 Dashboard

Open `http://<uno-q-ip>:8931/` on your laptop. If an older version of the page
was open before, reload it with Ctrl+Shift+R.

**Live tab**

- [ ] Header shows `N of N online` (green). Fewer than all online turns it orange.
- [ ] One row per device, in UID order: 1:1, 1:2 ... 1:9, 1:10 (not 1:1,
      1:10, 1:2), then by Device ID. A node that comes online later appears
      in its place.
- [ ] A **Device ID** column right after **Part** shows each node's MAC.
      Two nodes with the same UID show as two rows, e.g.
      `1:1 | 44:1D:64:...:01` and `1:1 | 44:1D:64:...:02`.
- [ ] Values and age change in place every 5 s; the table does not flicker
      or jump.
- [ ] A node that stops sending fades (greyed row) after 60 s; its last
      values, age, status and delivery stay visible.
- [ ] A node with no stored readings shows `(none)`, and `-` for Age,
      Status and Delivery, on a greyed row.
- [ ] A sensor fault shows a red `FAULT`.

**History tab**

Leave the gateway running for about 30 minutes first, so the charts have
something to show.

- [ ] The address changes to `.../#history`; reloading the page stays on
      History.
- [ ] One grid of charts, in node order. The top line of each card shows the
      node: status dot, UID, `· MAC`, part, `ok`/`FAULT` and delivery.
- [ ] Two devices with the same UID get separate cards; their lines are not
      mixed.
- [ ] A node with a sensor fault shows `FAULT` and a red border on every one
      of its cards.
- [ ] Each chart has a unit, value and time axes, mean / min / max, and the
      current value on the right.
- [ ] Window buttons are 1 h, 12 h (selected at start), 24 h, 7 d.
- [ ] The min/max band disappears when "Min/max band" is unticked.
- [ ] Hovering a chart shows the time and value; "Expand" makes it full width.
- [ ] The Sensor dropdown lists one entry per device.
- [ ] Turn one node off for 5 minutes and back on: its charts show a grey
      `offline` gap instead of a straight line.
- [ ] Add a note, e.g. `bash gateway.sh tool annotate "fan on" 1:6`:
      it appears as an orange marker on the charts after switching window
      or reloading.

### 1.8 MCP server

In a second terminal on the board:

```
cd IEEE-BLP-AIoT-Stack
bash gateway.sh mcp
```

From your laptop, connect an MCP client to `http://<uno-q-ip>:8000/mcp`. With
Claude Code:

```
claude mcp add --transport http aiot-gateway http://<uno-q-ip>:8000/mcp
```

Then ask, for example, "list the sensors and read the latest CO2".

Device ID checks (from the board, no LLM needed):

```
bash gateway.sh tool list_sensors                 # one entry per device, with "mac"
bash gateway.sh tool read_latest 1:1              # several devices: a "devices" list
bash gateway.sh tool read_latest 1:1 --mac <MAC>  # just that device
```

A UID with one device gives the plain answer plus its `mac`.

### 1.9 Check InfluxDB directly

```
influx -database aiot_blp -execute 'SHOW RETENTION POLICIES'
influx -database aiot_blp -execute 'SHOW CONTINUOUS QUERIES'
influx -database aiot_blp -execute 'SELECT count(*) FROM raw.readings'
influx -database aiot_blp -execute 'SHOW TAG VALUES FROM raw.readings WITH KEY = "mac"'
```

Expected:

- retention policies `raw` (168h, default: true), `rollup` (8736h) and
  `autogen`
- one continuous query, `cq_rollup`
- a non-zero count that grows each time you rerun the count
- one `mac` value per powered node

After about 10 minutes of `run`:

```
influx -database aiot_blp -execute 'SELECT count(*) FROM rollup.readings_rollup'
```

A non-zero count means the 5-minute rollup is working.

### 1.10 Old SQLite data (optional)

Only if `gateway/data/gateway.db` exists from earlier SQLite runs and you want
that history in InfluxDB. Stop `run` and `mcp` (Ctrl+C) first, then:

```
bash gateway.sh migrate-sqlite --dry-run
bash gateway.sh migrate-sqlite
```

The dry run prints what would be copied without writing anything.
`gateway.db` itself is left untouched. A `gateway.db` from before the Device
ID change has no MACs; its sensors come across with an empty Device ID.

### Phase 1 done when

- [ ] both smoke tests and the Device ID test pass
- [ ] simulate `--twin 1` shows 15 rows, `1:1` twice
- [ ] `run` shows `BLE scan mode: passive` and real nodes, with their MACs
- [ ] Dashboard Live and History checks in 1.7 pass
- [ ] MCP answers from your laptop
- [ ] `raw.readings` grows and `rollup.readings_rollup` fills after ~10 min

---

## Install Docker (Ubuntu and Debian)

Skip this if `docker --version` and `docker compose version` already work.
The Uno Q runs Debian, an Ubuntu PC runs Ubuntu; the commands below work on
both (they read which one from `/etc/os-release`).

**Use Docker Engine from Docker's own repository.** Not:

- **Docker Desktop**: it runs containers inside a virtual machine, so the
  gateway cannot reach the host's Bluetooth.
- **The snap** (`snap install docker`): it cannot reach `/run/dbus`, which the
  gateway needs for Bluetooth, nor folders outside your home folder.
- **Ubuntu's `docker.io` package**: it works, but is often older and lacks
  the `docker compose` plugin.

### Remove old or conflicting packages

```
sudo snap remove docker 2>/dev/null
for p in docker.io docker-doc docker-compose docker-compose-v2 podman-docker containerd runc; do
  sudo apt-get remove -y $p
done
```

"not installed" messages are fine. Images and volumes from an earlier Docker
in `/var/lib/docker` are kept.

### Add Docker's repository

```
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
. /etc/os-release
sudo curl -fsSL https://download.docker.com/linux/$ID/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/$ID ${UBUNTU_CODENAME:-$VERSION_CODENAME} stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt-get update
```

The last command should list `download.docker.com` without errors. `$ID` is
`ubuntu` or `debian`; on another distribution (Linux Mint, Raspberry Pi OS,
...) see Docker's install page for that system.

### Install and start

```
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
```

`enable` makes Docker, and with it the stack, start again after a reboot.

### Use Docker without sudo

```
sudo usermod -aG docker $USER
```

Log out and back in (or reboot) for it to apply; `groups` then lists
`docker`. Membership of the `docker` group is equivalent to root on this
machine; add only trusted users.

### Check

```
docker --version
docker compose version
docker run --rm hello-world
```

Expected: a version for each, then `Hello from Docker!`. Remove the test
image again with `docker image rm hello-world`.

### Before the first build

- *(Uno Q only)* Move Docker's data to `/home` now, while it is empty
  (section "Disk space", "Move Docker's data to /home"). A PC usually has
  room on `/`; check with `df -h /`.
- Optional: cap the logs of every container on the machine, not only this
  stack's (`compose.yaml` already caps its own). Create
  `/etc/docker/daemon.json`, or add the two log lines if it already exists:

  ```
  {
      "log-driver": "json-file",
      "log-opts": { "max-size": "10m", "max-file": "2" }
  }
  ```

  then `sudo systemctl restart docker`.

Continue with Phase 2. On a machine that skipped Phase 1, start at 2.2.

---

## Phase 2: Docker

### 2.1 Stop the Phase 1 setup

Only if you ran Phase 1 on this machine.


- Ctrl+C both `run` and `mcp`.
- Optional: back up the data collected in Phase 1:

  ```
  influxd backup -portable -db aiot_blp ~/aiot_blp_backup
  ```

- Stop the native InfluxDB so only the container's runs:

  ```
  sudo systemctl disable --now influxdb
  ```

Ports 8931, 8000, 3000, 8888 and 8501 must be free:
`ss -ltnp | grep -E ':8931|:8000|:3000|:8888|:8501'` should print nothing.

### 2.2 Check Docker

```
docker --version
docker compose version
docker info --format '{{.DockerRootDir}}'
```

If `docker` is not found, see "Install Docker". If Docker commands need
`sudo`, add yourself to the `docker` group once, then log out and back in:

```
sudo usermod -aG docker $USER
```

`DockerRootDir` is where Docker keeps images, containers and volumes.
*(Uno Q only)* The default, `/var/lib/docker`, is on the Uno Q's small root
partition. Move it to `/home` **before** the first build (section "Disk
space", "Move Docker's data to /home").

### 2.3 Create the settings file

```
cp .env.example .env
```

The defaults are fine for a first test: InfluxDB backend, database
`aiot_blp`, raw 7d, rollup 5m kept 52w, dashboard on 8931, MCP on 8000,
Grafana on 3000, JupyterLab on 8888, Streamlit on 8501. `.env` is not
tracked by git.

JupyterLab token: `JUPYTER_TOKEN`, default `radiostudio`, also public.
Anyone with it can run commands in the `jupyter` container, so change it on
a shared network. Unlike the Grafana password it can be changed at any time
(edit `.env`, then `docker compose up -d`). Streamlit has no login.

Grafana admin password: `GRAFANA_ADMIN_PASSWORD`, default `radiostudio`. That
default is public in the repository; if the board is on a shared network,
change it in `.env` **now**. Grafana reads it only on its first start.

### 2.4 Restore the Phase 1 data (optional)

Only if you made the backup in 2.1 **with Device ID code** (`8892218` or
later). Older backups have no MACs and the gateway refuses them. Do this
**before** the gateway starts:

```
docker compose up -d influxdb
docker compose cp ~/aiot_blp_backup influxdb:/tmp/aiot_blp_backup
docker compose exec influxdb influxd restore -portable -db aiot_blp /tmp/aiot_blp_backup
```

### 2.5 Build and start the stack

```
docker compose up -d --build
docker compose ps
docker compose logs -f gateway
```

The first build downloads about 170 MB of Python packages and pulls the
InfluxDB and Grafana images. All packages have ready-built arm64 versions, so
nothing is compiled. The image is built once and used by both `gateway` and
`mcp`.

Expected:

- `docker compose ps`: `influxdb` is `healthy`; `gateway`, `mcp`,
  `grafana`, `jupyter` and `streamlit` are `running`
- `docker images` shows one `aiot-blp-gateway   local` image and no `<none>`
  image from this build
- the gateway log shows
  - `[gateway] store: influx (aiot_blp @ http://influxdb:8086) ...`
  - `[gateway] BLE scan mode: passive`
  - your nodes coming `online`, each with its MAC

Ctrl+C leaves the log view; the containers keep running.

### 2.6 Tests inside the container

```
docker compose run --rm gateway smoke --backend influx
docker compose exec gateway python -m gateway.tests.test_multi_device influx
```

Expected: `SMOKE TEST PASSED`, then the `ok:` lines ending with
`ok: influx_two_devices`.

Analysis libraries in the image:

```
docker compose exec gateway python -c "import pandas, polars, pyarrow, cbor2, matplotlib, plotly, influxdb, influxdb_client, sklearn, sktime, streamlit, jupyterlab; print('ok', matplotlib.get_backend())"
```

Expected: `ok agg`.

### 2.7 Same checks as Phase 1

- Dashboard: `http://<uno-q-ip>:8931/`, the Live and History checks in 1.7.
- MCP: `http://<uno-q-ip>:8000/mcp`. The device checks in 1.8 work with
  `docker compose exec gateway python -m gateway tool ...` in place of
  `bash gateway.sh tool ...`.
- Data: the queries in 1.9, prefixed with `docker compose exec influxdb`,
  e.g.

  ```
  docker compose exec influxdb influx -database aiot_blp -execute 'SELECT count(*) FROM raw.readings'
  ```

- Log caps:

  ```
  docker inspect --format '{{.Name}} {{.HostConfig.LogConfig.Config}}' $(docker compose ps -q)
  ```

  Every line shows `map[max-file:3 max-size:10m]`.

### 2.8 Grafana

Open `http://<uno-q-ip>:3000/` on a laptop and on a phone.

- [ ] The **AIoT sensors** dashboard opens straight away, with no login
- [ ] Top bar: **Source** (`raw`), **Sensor** (`All`), **Device** (`All`),
      **Field** (`All`), **Journal** switch
- [ ] One chart per field, one line per device; the legend reads
      `<uid> <MAC>`, e.g. `1:1 44:1D:64:C1:34:32`
- [ ] Lines move on their own (refresh every 10 s, top right)
- [ ] **Sensor** = one UID: only its devices' lines; **Device** then lists
      only that UID's MACs
- [ ] **Device** = one MAC: only that device's lines
- [ ] **Field** = two fields: only those two charts
- [ ] **Last frame per device** at the bottom: one row per device, with a
      **Device ID** column, `a few seconds ago`, in UID order
- [ ] Add a note:
      `docker compose exec gateway python -m gateway tool annotate "fan on" 1:6`.
      Within 10 s an orange dashed line appears on the charts
- [ ] **Source** = `rollup` with "Last 1 hour": after 10 minutes, the lines
      are 5-minute points, still one per device
- [ ] Sign in (bottom left) as `admin` / your `GRAFANA_ADMIN_PASSWORD`. Change
      something and try to save: Grafana refuses ("Cannot save provisioned
      dashboard"); **Save as** works
- [ ] As a viewer (signed out or private window) there is no edit or save

If an older copy of the dashboard is still shown (no **Device** dropdown),
`docker compose restart grafana`.

### 2.9 Jupyter and Streamlit

Both run from the gateway image and work in the repository's `analysis/`
folder: `aiot_data.py` (reads InfluxDB into pandas), `example.ipynb` and
`streamlit_app.py`.

**JupyterLab**: open `http://<uno-q-ip>:8888/` on a laptop.

- [ ] A login page asks for a password or token: enter your `JUPYTER_TOKEN`
- [ ] The file list on the left shows `aiot_data.py`, `example.ipynb`,
      `streamlit_app.py`
- [ ] Open `example.ipynb`, then Run, Run All Cells. With the gateway
      running for at least 10 minutes:
  - [ ] the first cell prints `InfluxDB: http://influxdb:8086 database
        aiot_blp`, `Times are shown in: Asia/Kolkata` and a table with one
        row per device
  - [ ] the readings table shows times ending in `+05:30` (IST), close to
        the clock on your laptop
  - [ ] the plots show inside the notebook
  - [ ] "unusual readings" marks points in red (scikit-learn)
  - [ ] the forecast prints two mean absolute errors and a chart (sktime).
        With less than 10 minutes of data it says so instead; run the cell
        again later
  - [ ] the last cell lists the MCP tools and prints `read_latest` for the
        chosen sensor (MCP client)
- [ ] File, New, Notebook: a new notebook appears in `analysis/` on the
      board (`ls analysis`)
- [ ] In that notebook, a cell with `!date` prints the time with `IST`.
      `UTC` means the time zone is not set: see the troubleshooting table

**Streamlit**: open `http://<uno-q-ip>:8501/`.

- [ ] Title **AIoT sensors**; on the left Sensor, Device (only for a sensor
      with more than one device), Field and Window
- [ ] A value per device, a line chart (one colour per device) and a table
      of count / mean / min / max / std
- [ ] The values move on their own every 10 s
- [ ] A different Sensor or Field changes the chart
- [ ] Edit `analysis/streamlit_app.py` on the board (e.g. change the title)
      and save: the page reloads with the change

From a phone or another laptop on the same network both addresses work too.

### 2.10 Restarts

```
docker compose restart
```

The dashboard history should still be there.

```
sudo reboot
```

After the board comes back, `docker compose ps` (from the repository folder)
should show all six containers running again without any action from you,
and the data, the Grafana admin login and any "Save as" dashboards should
still be there.

### Phase 2 done when

- [ ] the image builds on the board, once (no `<none>` image left behind)
- [ ] `influxdb` is healthy; `gateway`, `mcp`, `grafana`, `jupyter` and
      `streamlit` are running
- [ ] the smoke and Device ID tests pass inside the container
- [ ] `BLE scan mode: passive` and real nodes, with MACs, on the dashboard
- [ ] dashboard Live and History checks (1.7) pass
- [ ] MCP answers from your laptop
- [ ] Grafana checks (2.8) pass, on a laptop and a phone
- [ ] Jupyter and Streamlit checks (2.9) pass
- [ ] log caps show `max-file:3 max-size:10m`
- [ ] data and History survive `docker compose restart` and a reboot

---

## Maintaining the Docker stack

### Docker in five minutes

| Word | What it is here |
|---|---|
| **Image** | A read-only package: an operating system layer, Python, the libraries and the gateway code. `aiot-blp-gateway:local` is built on the board from `Dockerfile`; `influxdb:1.13.1` and `grafana/grafana:13.2.5` are downloaded. Changing the code means building a new image. |
| **Container** | A running copy of an image. This stack has six: `influxdb`, `gateway`, `mcp`, `grafana`, `jupyter`, `streamlit` (`gateway`, `mcp`, `jupyter` and `streamlit` are four containers from the same image). Anything a container writes outside a volume is lost when it is recreated. |
| **Volume** | Storage that outlives containers. `influxdb-data` holds the InfluxDB data; `grafana-data` holds Grafana's own database (admin login, "Save as" dashboards). Docker keeps them under its data folder. |
| **Bind mount** | A host folder shown inside a container. `./gateway/data` (SQLite inventory, rules, token) and `./docker/grafana/...` are bind mounts: you can edit or copy those files directly on the board. |
| **Compose** | `compose.yaml` describes the six containers, their ports, volumes and settings. `docker compose ...` commands act on all of them (or on the ones you name), and must be run **from the repository folder**. |
| **`.env`** | Settings read by compose (database name, retention, ports, Grafana password). |

Which command for which change:

| You changed | Run |
|---|---|
| Nothing; just restart | `docker compose restart` (or `restart gateway`) |
| `.env` or `compose.yaml` | `docker compose up -d` (recreates only what changed) |
| Python code, `Dockerfile`, requirements, the shipped cards (without the cards mount below) | `docker compose up -d --build` |
| A card, with the cards mount below | `docker compose restart gateway mcp` |
| A rule file in `gateway/data/rules.d/` | `docker compose restart gateway` |
| Grafana dashboard JSON in `docker/grafana/dashboards/` | nothing; Grafana rereads it within a minute (or `docker compose restart grafana`) |
| `analysis/streamlit_app.py` | nothing; the open page reloads on save |
| A notebook or `analysis/aiot_data.py` | in JupyterLab, Kernel, Restart Kernel (to re-import `aiot_data`) |

`up -d` = create and start in the background; `--build` = build the image
first. Recreating a container keeps volumes and bind-mounted files.

### Where everything lives

| What | Where | Survives `down`? | Survives `down -v`? |
|---|---|---|---|
| Readings, rollups, notes (InfluxDB) | volume `aiot-blp_influxdb-data` | yes | **no** |
| Sensor inventory (uid, MAC, part, counts) | `gateway/data/gateway_meta.db` | yes | yes |
| Everything (SQLite backend only) | `gateway/data/gateway.db` | yes | yes |
| Approved rules, MCP token | `gateway/data/rules.d/` | yes | yes |
| Grafana login, "Save as" dashboards | volume `aiot-blp_grafana-data` | yes | **no** |
| Notebooks, Streamlit app, `aiot_data.py` | `analysis/` (repo; your own files there are not tracked until you `git add` them) | yes | yes |
| Provisioned Grafana dashboard | `docker/grafana/dashboards/aiot_sensors.json` (repo) | yes | yes |
| Sensor cards | inside the image, from `gateway/cards/` (or mounted, see below) | yes | yes |
| Container logs | Docker's data folder, 3 x 10 MB per container | no | no |

### Are the services running?

```
docker compose ps
```

| STATUS column | Meaning |
|---|---|
| `Up 5 minutes` | running |
| `Up 5 minutes (healthy)` | running and its health check passes (`influxdb` only) |
| `Up ... (health: starting)` | `influxdb` still starting; the others wait for it |
| `Restarting (1) ...` | crashes and restarts again and again: read its log |
| `Exited (1) ...` or missing | stopped: read its log, then `docker compose up -d` |

`docker compose ps -a` also lists stopped containers.

Quick checks from the board:

```
curl -s localhost:8931/api/sensors | head -c 300; echo   # dashboard + gateway
curl -s -o /dev/null -w '%{http_code}\n' localhost:3000/api/health   # Grafana: 200
curl -s -o /dev/null -w '%{http_code}\n' localhost:8501/_stcore/health   # Streamlit: 200
curl -s -o /dev/null -w '%{http_code}\n' localhost:8888/login         # JupyterLab: 200
docker compose exec influxdb influx -execute 'SHOW DATABASES'        # InfluxDB
docker stats --no-stream                                             # CPU and memory per container
```

Is it actually receiving? The `last_seen` of every device:

```
docker compose exec gateway python -m gateway tool list_sensors
```

### Logs

```
docker compose logs -f gateway            # follow live; Ctrl+C stops following only
docker compose logs --tail 100 gateway    # last 100 lines
docker compose logs --since 30m gateway   # the last 30 minutes
docker compose logs -t gateway            # with timestamps
docker compose logs -f                    # all six, interleaved
docker compose logs gateway | grep -i error
```

Services: `gateway` (BLE, decoding, dashboard), `mcp`, `influxdb`, `grafana`,
`jupyter`, `streamlit`. Python errors from a notebook show in the notebook,
not in the log; errors from the Streamlit app show on its page and in
`docker compose logs streamlit`.
What a healthy gateway log looks like: `store: influx (...)`, `BLE scan mode:
passive`, then one `<uid> <MAC> (<part>) online: ...` line per node.

Logs are capped at 3 files of 10 MB per container; the oldest is dropped.
Recreating a container (`up -d` after a change, `down`) starts a new log.
Save one before that if you need it:

```
docker compose logs --no-color gateway > ~/gateway-$(date +%F).log
```

### Start, stop, restart

| Task | Command |
|---|---|
| Start everything (or after a change) | `docker compose up -d` |
| Restart one service | `docker compose restart gateway` |
| Stop one service, keep it | `docker compose stop gateway` (start it: `docker compose start gateway`) |
| Stop and remove the containers (data kept) | `docker compose down` |
| Same, **and delete InfluxDB and Grafana data** | `docker compose down -v` |
| Shell inside a container | `docker compose exec gateway bash` (`exit` to leave) |
| One gateway command in a fresh container | `docker compose run --rm gateway <command>`, e.g. `smoke` |

All six have `restart: unless-stopped`: after a crash or a reboot they come
back on their own, unless you stopped them yourself.

The gateway's CLI inside the container: `docker compose exec gateway python
-m gateway <command>` runs the same commands as `bash gateway.sh <command>`
natively (`tool`, `liveness`, `recipe`, `approve-rule`, `token`, ...).

### Update to a newer version of the code

```
git pull
docker compose up -d --build
docker image prune -f
docker compose ps
```

The build reuses the cached package layer unless `gateway/requirements*.txt`
changed, so a code-only update takes seconds. `docker image prune -f`
removes the previous image, which the rebuild leaves as `<none>`.

If the release notes say the database format changed, follow "Reset
everything" first.

### Add a new sensor card without rebuilding

Cards are read from `/app/gateway/cards/` **inside the image**, and only when
the gateway or MCP server starts. As shipped, a new card means
`docker compose up -d --build` (quick, the packages are cached).

To add cards without rebuilding, show the board's `gateway/cards/` folder to
the containers. Once, create `compose.override.yaml` next to `compose.yaml`
(compose reads it automatically; it is board-local, do not commit it):

```
cat > compose.override.yaml <<'EOF'
# board-local: cards from the host folder instead of the image
services:
  gateway:
    volumes:
      - ./gateway/cards:/app/gateway/cards:ro
  mcp:
    volumes:
      - ./gateway/cards:/app/gateway/cards:ro
EOF
docker compose up -d
docker compose exec gateway ls /app/gateway/cards
```

Then, for each new card:

1. Copy the card JSON into `gateway/cards/`, e.g. `19_mysensor.json`.
   `sensor_type_id` must match what the firmware sends, and must not be used
   by another card. Use an existing card (e.g. `17_sht40.json`) as a template.
2. Check that it is valid JSON:
   ```
   python3 -m json.tool gateway/cards/19_mysensor.json > /dev/null && echo ok
   ```
3. Load it:
   ```
   docker compose restart gateway mcp
   docker compose exec gateway python -m gateway tool describe_sensor 1:19
   ```
4. Power the node. Its row appears on the dashboard, its fields appear in
   Grafana's **Field** list (read from the data), and the MCP tools know
   its plausibility bounds. Nothing else to change.

To edit a card, change the file and `docker compose restart gateway mcp`.
To go back to the cards in the image: delete `compose.override.yaml`, then
`docker compose up -d`.

Without the override, the alternative is `docker compose cp` into the
container, but the card is lost the next time the container is recreated;
use it only for a quick test.

### Look at the data

**InfluxDB (readings, rollups, notes).** Open its shell:

```
docker compose exec influxdb influx -database aiot_blp -precision rfc3339
```

then type queries (`exit` to leave):

```
SHOW MEASUREMENTS
SHOW TAG VALUES FROM raw.readings WITH KEY = "sensor_uid"
SHOW TAG VALUES FROM raw.readings WITH KEY = "mac"
SHOW FIELD KEYS FROM raw.readings
SELECT * FROM raw.readings WHERE sensor_uid = '1:1' ORDER BY time DESC LIMIT 5
SELECT temperature_c, mac FROM raw.readings WHERE sensor_uid = '1:1' AND mac = '44:1D:64:C1:34:32' AND time > now() - 10m
SELECT count(*) FROM raw.readings GROUP BY sensor_uid, mac
SELECT * FROM rollup.readings_rollup WHERE sensor_uid = '1:1' ORDER BY time DESC LIMIT 5
SELECT * FROM annotations ORDER BY time DESC LIMIT 10
```

Layout: measurement `readings` in retention policy `raw` (7 days); tags
`sensor_uid`, `kit_id`, `sensor_type_id`, `mac`; one field per measurand
(`temperature_c`, `co2_ppm`, ...) plus `seq`, `status`, `rx_time`. Rollups:
`rollup.readings_rollup` with `mean_<field>`, `min_<field>`, `max_<field>`,
`count_<field>`. Notes: `annotations`. String values go in single quotes,
names with special characters in double quotes. One-off queries without the
shell: add `-execute '<query>'`.

Export to CSV:

```
docker compose exec influxdb influx -database aiot_blp -format csv \
  -execute "SELECT * FROM raw.readings WHERE time > now() - 1h" > ~/readings.csv
```

**SQLite inventory (`gateway/data/gateway_meta.db`).** It is a normal file on
the board. Install the tool once (`sudo apt install sqlite3`), then:

```
sudo sqlite3 -header -column gateway/data/gateway_meta.db
```

```
.tables
SELECT uid, mac, part, datetime(last_seen, 'unixepoch', 'localtime') AS last_seen, rx_count, lost_count FROM sensors ORDER BY uid, mac;
.quit
```

The files belong to root (the containers write them), hence `sudo`. Read-only
while the stack runs is fine.

**Python / pandas**, for analysis: put a script in `gateway/data/` and run
`docker compose exec gateway python /app/gateway/data/<script>.py`. From
inside the container InfluxDB is `host='influxdb'`.

### Delete or change data

Stop the writers first, so they do not put back what you delete:

```
docker compose stop gateway mcp
```

Then, in the InfluxDB shell (`docker compose exec influxdb influx -database aiot_blp`):

| Delete | Query |
|---|---|
| One device's readings | `DELETE FROM readings WHERE sensor_uid = '1:1' AND mac = 'AA:BB:CC:DD:EE:FF'` |
| A sensor's readings, all devices | `DELETE FROM readings WHERE sensor_uid = '1:1'` |
| A time range | `DELETE FROM readings WHERE time > '2026-11-06T10:00:00Z' AND time < '2026-11-06T11:00:00Z'` |
| The matching rollups | the same queries with `readings_rollup` |
| All notes | `DROP MEASUREMENT annotations` |

`DELETE` takes no retention policy (it covers `raw` and `rollup` alike) and
filters only on tags and time, not on values. Readings older than the raw
retention (`INFLUX_RAW_RETENTION`, 7 days) are deleted by InfluxDB on its own.

And in the inventory (`sudo sqlite3 gateway/data/gateway_meta.db`), for
example to forget a stray device:

```
DELETE FROM sensors WHERE uid = '1:1' AND mac = 'AA:BB:CC:DD:EE:FF';
```

Then `docker compose start gateway mcp`. A device that is still sending comes
back with its next frame.

**Changing** values: InfluxDB has no `UPDATE`. A point written again with the
same time, measurement and tags replaces the old one, but a wrong value is
normally better left alone and explained with a note
(`tool annotate "probe was out of the water" 1:1`), or deleted with the
queries above. For the inventory, normal SQL `UPDATE` works with the gateway
stopped, e.g. `UPDATE sensors SET part = 'DS18B20 tank' WHERE uid = '1:1' AND mac = '...';`,
though the gateway sets `part` from the card again on the next frame.

**Always back up before deleting** (next section).

### Back up and restore

Back up (the stack keeps running; stop `gateway mcp` first for an exact
snapshot of the inventory):

```
B=~/backup/$(date +%F) && mkdir -p $B
sudo cp gateway/data/gateway_meta.db* $B/
sudo cp -r gateway/data/rules.d $B/
docker compose exec influxdb rm -rf /tmp/influx-bk
docker compose exec influxdb influxd backup -portable -db aiot_blp /tmp/influx-bk
docker compose cp influxdb:/tmp/influx-bk $B/influx
sudo chown -R $USER: $B && ls -R $B | head
```

Restore (into an empty `aiot_blp`):

```
docker compose stop gateway mcp
docker compose exec influxdb influx -execute 'DROP DATABASE aiot_blp'
docker compose cp $B/influx influxdb:/tmp/influx-restore
docker compose exec influxdb influxd restore -portable -db aiot_blp /tmp/influx-restore
sudo cp $B/gateway_meta.db* gateway/data/
docker compose start gateway mcp
```

A backup restores only with code that has the same database format (for now:
`8892218` or later).

### Reset everything

Start with empty databases (e.g. after "old database format", or before a
workshop). Back up first (above), then:

```
docker compose stop gateway mcp
sudo rm -f gateway/data/gateway_meta.db* gateway/data/gateway.db*
docker compose exec influxdb influx -execute 'DROP DATABASE aiot_blp'
docker compose up -d
```

The gateway recreates the database, retention policies, rollup query and
inventory at start. Rules and the token in `rules.d/` are kept.

Native (Phase 1) equivalent: stop `run` and `mcp`, then
`rm -f gateway/data/gateway_meta.db* gateway/data/gateway.db*` and
`influx -execute 'DROP DATABASE aiot_blp'`.

Wipe everything including Grafana's login and "Save as" dashboards:
`docker compose down -v`, remove the files above, `docker compose up -d`.

### Settings (`.env`)

Edit `.env`, then `docker compose up -d`. Compose recreates only the
containers whose settings changed. Shortening a retention deletes older data.

**Time zone (`TZ`, default `Asia/Kolkata`, IST).** Sets the clock in
JupyterLab and Streamlit (`datetime.now()`, `!date`) and the time zone of
the times `aiot_data` returns, so notebook tables and charts show IST.
Other zones: a name from the tz database, e.g. `Europe/London` or `UTC`.
InfluxDB always stores UTC; that is correct and does not change. The
gateway dashboard, Grafana and Streamlit's charts show times in the
viewer's browser time zone, whatever `TZ` says. The image contains the time
zone files from this version on: after the update that added them, run
`docker compose up -d --build` once.

`GRAFANA_ADMIN_PASSWORD` is read only on Grafana's first start; to change it
later:

```
docker compose exec grafana grafana cli admin reset-admin-password <new>
```

### Disk space

The root partition on the Uno Q is small (about 10 GB). Check it regularly:

```
df -h / /home
docker system df              # images, containers, volumes, build cache
docker system df -v           # per image and per volume
```

`docker images` shows each image's full size, but images share layers, so
`docker system df` is the real total. `du` on `/var/lib/docker` without
`-x` counts running containers twice and overstates it.

Safe clean-up (nothing in use is touched):

| Command | Removes |
|---|---|
| `docker image prune -f` | `<none>` images left by rebuilds |
| `docker builder prune -af` | the build cache (the next build downloads the packages again) |
| `docker container prune -f` | stopped containers |
| `docker system prune -f` | all three of the above except the full build cache |

**Never** `docker volume prune` or `docker system prune --volumes` unless you
want to delete the InfluxDB and Grafana data.

**Move Docker's data to /home** *(Uno Q only)* (once per board, about 10 minutes; Docker is
down meanwhile):

```
docker compose down
sudo systemctl stop docker docker.socket containerd
sudo mkdir -p /home/arduino/docker-data
sudo rsync -aHAX --info=progress2 /var/lib/docker/ /home/arduino/docker-data/
sudo mv /var/lib/docker /var/lib/docker.old
```

Edit `/etc/docker/daemon.json` (`sudo nano /etc/docker/daemon.json`). Keep any
settings already there and add `data-root`; the whole file, if it held only
the log options:

```
{
    "data-root": "/home/arduino/docker-data",
    "log-driver": "json-file",
    "log-opts": { "max-size": "10m", "max-file": "2" }
}
```

Do not use `echo ... | sudo tee` on this file; it replaces the whole file.
Check it and start Docker again:

```
python3 -m json.tool /etc/docker/daemon.json
sudo systemctl start docker
docker info --format '{{.DockerRootDir}}'   # /home/arduino/docker-data
docker compose up -d
docker compose ps
```

When the dashboard and Grafana show the old history, free the root
partition: `sudo rm -rf /var/lib/docker.old`.

### Grafana

- Viewers need no login. Admin: `admin` / `GRAFANA_ADMIN_PASSWORD`.
- The **AIoT sensors** dashboard comes from
  `docker/grafana/dashboards/aiot_sensors.json` and cannot be saved over in
  the browser. Either **Save as** a copy (kept in the `grafana-data` volume),
  or edit the JSON file (Dashboard settings, JSON Model, copy into the file),
  then `docker compose restart grafana`.
- "Data source aiot-influx not found" or a broken Grafana after the disk
  filled up: free space, then
  `docker compose stop grafana && docker volume rm aiot-blp_grafana-data && docker compose up -d grafana`
  (removes "Save as" copies and resets the admin password to `.env`).

### Install on a second Uno Q

Build on the new board (simplest; needs internet): the steps from 1.1 and
Phase 2. Or copy the images from a working board, without internet on the
new one:

```
# on the working board
docker save aiot-blp-gateway:local influxdb:1.13.1 grafana/grafana:13.2.5 | gzip > ~/aiot-images.tar.gz
# copy the file and the repository folder to the new board, then there:
gunzip -c ~/aiot-images.tar.gz | docker load
cp .env.example .env
docker compose up -d          # no --build
```

Data is not copied this way; use "Back up and restore" for that.

### Classroom use (many students in Jupyter)

All students share one JupyterLab: they log in with the same token, and
each open notebook runs its own Python process (a "kernel") on the gateway
machine. The limit is memory, not the number of logins.

**How much memory.** Measured per open notebook:

| Notebook | Memory |
|---|---|
| Only pandas imported | about 110 MB |
| pandas, matplotlib and scikit-learn | about 220 MB |
| `example.ipynb`, all cells run | about 300 to 400 MB |

On the Lenovo X1 Carbon (31 GB, about 24 GB free with the whole stack
running): 50 students × 350 MB ≈ 17.5 GB, so 50 students fit. Check the
free memory of your machine with `free -h` (column `available`).

Two settings in `.env` protect the rest of the stack:

| Setting | Default | What it does |
|---|---|---|
| `JUPYTER_MEMORY_LIMIT` | `20g` | All notebooks together may use at most this. Above it, Docker stops the largest notebook; the gateway, InfluxDB and Grafana keep running. Set it a few GB below the `available` memory |
| `JUPYTER_IDLE_SECONDS` | `900` (15 min) | A notebook that has run nothing for this long is stopped, even if its tab is still open. Its file is kept; only the variables in memory are lost |

On a machine with less memory, e.g. the Uno Q, lower the limit, e.g.
`JUPYTER_MEMORY_LIMIT=2g`, and plan for fewer students.

**Before class**

```
nano .env                     # set JUPYTER_TOKEN, JUPYTER_MEMORY_LIMIT, JUPYTER_IDLE_SECONDS
docker compose up -d jupyter  # restarts JupyterLab with the new settings
free -h                       # enough memory available?
```

Tell the students: the address (`http://<gateway-ip>:8888/`) and the token.

**Each student works in their own folder.** Everyone sees the same files.
If two students open the same notebook, they overwrite each other's work.
So each student first:

1. In JupyterLab's file list on the left: the **New Folder** button, and
   names it after themselves, e.g. `priya`.
2. Right-click `example.ipynb`, **Copy**; open their folder, right-click,
   **Paste**.
3. Works only in the copy inside their folder.

For the Streamlit exercise (`analysis/README.md`) the page file goes in
`analysis/pages/`, so it needs a unique name too, e.g. `priya_app.py`.

**During class**

```
docker stats --no-stream      # MEM USAGE / LIMIT of the jupyter row
```

In JupyterLab, the **Running** panel (the square-in-circle icon on the
left) lists the open notebooks; the ■ next to one stops it.

**"Kernel died" or variables gone.** The notebook was stopped: idle too
long, or the memory limit was reached. The file is not lost. In the
notebook: **Kernel → Restart Kernel and Run All Cells**. If it keeps
happening during class, `docker stats` shows whether the memory is full;
ask students to close the notebooks they are not using
(**File → Close and Shut Down Notebook**).

**After class:** keep a copy of the students' work, then clean up.

```
tar czf ~/analysis-$(date +%F).tar.gz analysis    # backup of analysis/
sudo rm -r analysis/priya                         # one student folder
```

Do not delete `aiot_data.py`, `example.ipynb`, `streamlit_app.py`,
`README.md` or the `pages` folder itself (`git status` shows what is not
part of the repository).

---

## Going back from Docker to native

- `docker compose down`, then `sudo systemctl enable --now influxdb`.
- Files the containers wrote in `gateway/data` may be owned by root. If the
  native gateway gets a permission error there:

  ```
  sudo chown -R $USER: gateway/data
  ```

- Native and Docker use separate InfluxDB data: the board's
  `/var/lib/influxdb` and the `influxdb-data` Docker volume. Data written in
  one is not visible in the other unless you back it up and restore it.

---

## If something fails

| Symptom | Likely cause / fix |
|---|---|
| `old database format` and the gateway exits | Database from before the Device ID change: back up, then "Reset everything" |
| `InfluxDB not reachable at http://localhost:8086` (Phase 1) | Native InfluxDB not running: `sudo systemctl status influxdb` |
| `BLE scan mode: active (passive unavailable ...)` | BlueZ experimental mode is off; see "Before you start" |
| Bluetooth permission error (Phase 1) | Not in the `bluetooth` group yet; log out and back in after `setup.sh` |
| D-Bus `AccessDenied` / `NotPermitted` (Phase 2) | Check `security_opt: apparmor:unconfined` on `gateway` and that `/run/dbus/system_bus_socket` exists on the host |
| No adapter found | Set `GATEWAY_BLE_ADAPTER=hci0` in `.env` (Docker) or export it (native); see `bluetoothctl list` |
| `port is already allocated` | Something else (e.g. App Lab) uses 8931, 8000, 3000, 8888 or 8501; change the port in `.env` |
| A container shows `Restarting` | `docker compose logs --tail 50 <service>` |
| `influxdb` never becomes healthy | `docker compose logs influxdb`; often a full disk (`df -h`) |
| `no space left on device` | "Disk space": prune, then move Docker's data to /home |
| Build fails at `pip install` | Save the build log; most likely a package without an arm64 wheel, or no internet |
| `<none>` images in `docker images` | Old images left by rebuilds: `docker image prune -f` |
| `pull access denied for aiot-blp-gateway` when starting `mcp` | The image is not built yet: `docker compose up -d --build` |
| Dashboard empty, no errors | Wrong `GATEWAY_KIT_ID` filter; leave it empty to accept all kits |
| More Device IDs than powered nodes | Another nearby ESP32 sent a frame with your kit ID. Check its counts in `sensors` (one frame, no readings) and delete it ("Delete or change data") |
| No **Device ID** column / no **Device** dropdown | Old page or old image: Ctrl+Shift+R; `git log -1 --oneline` shows `3373c29` or later; `docker compose up -d --build`; `docker compose restart grafana` |
| New sensor logs `(no card) online` and shows no values | Image built without it, or no cards mount: `up -d --build`, or see "Add a new sensor card without rebuilding"; check the JSON and the `sensor_type_id` |
| Grafana asks for a login | Anonymous viewing is off: check `GF_AUTH_ANONYMOUS_ENABLED` in `compose.yaml`; `docker compose up -d` |
| Grafana admin password not accepted after changing `.env` | Read only on first start; use the reset command under "Settings" |
| Grafana dashboard missing or every chart "No data" | `docker compose logs grafana` for provisioning errors; check the time range and that `influxdb` is healthy |
| Grafana `rollup` source empty | Rollups appear after the first rollup period (default 5 min) |
| No orange note markers in Grafana | **Journal** switch off, or no notes in the time range |
| History chart says `no data in this window` | No readings for that field in the window; pick a longer one or wait |
| A greyed Live row with `(none)` and `-` everywhere | Known node with no readings stored (off for longer than the raw retention). Power the node |
| JupyterLab keeps showing its login page | Wrong token: it is `JUPYTER_TOKEN` in `.env` (default `radiostudio`); after changing `.env`, `docker compose up -d` |
| JupyterLab or Streamlit page does not open from another machine | `docker compose ps` shows the service running? Same network? Try `curl` on the machine itself (see "Are the services running?") |
| Notebook: `Cannot connect` / `Connection refused` to InfluxDB | `influxdb` not healthy, or the notebook runs outside Docker; inside the stack `aiot_data.INFLUX_URL` must be `http://influxdb:8086` |
| Notebook times are 5 h 30 min off, or `!date` says `UTC` | Times are in UTC: `TZ` missing in `.env` or an older container (`docker compose up -d`), or an image without time zone files (`docker compose up -d --build`). Check: `docker compose exec jupyter date` should print `IST` |
| Notebook plots do not show | The `jupyter` service sets `MPLBACKEND` for inline charts; in an older container run `%matplotlib inline` once, or `docker compose up -d` |
| Notebook: `ModuleNotFoundError` | The library is not in the image: add it to `gateway/requirements-docker.txt`, `docker compose up -d --build` |
| Notebook: "Kernel died" or variables gone | Stopped for being idle (`JUPYTER_IDLE_SECONDS`) or the memory limit was reached: Kernel → Restart Kernel and Run All Cells; see "Classroom use" |
| Students' notebooks keep dying during class | `docker stats --no-stream`: the jupyter row at its LIMIT? Close unused notebooks, or raise `JUPYTER_MEMORY_LIMIT` if `free -h` allows, then `docker compose up -d jupyter` |
| Cannot save or edit files in `analysis/` outside JupyterLab | They belong to root: `sudo chown -R $USER: analysis` |
| Streamlit: "Cannot read InfluxDB" | `influxdb` not healthy: `docker compose ps`, `docker compose logs influxdb` |
| Streamlit: "No readings in the last 24 hours" | No sensor has sent anything for a day; power a node |
| Log files growing without limit | Containers created before `d0524ec`: `git pull && docker compose up -d`, then check with the `docker inspect` line in 2.7 |

When reporting a problem, include the output of:

```
git log -1 --oneline
df -h / /home
docker compose ps
docker compose logs --tail 100 gateway
docker compose logs --tail 100 grafana   # Grafana problems
```
