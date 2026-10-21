# AIoT Gateway

Reference implementation of the gateway contract from
`../00_ARCHITECTURE_AND_CODE_STRUCTURE.md` Section 7: BLE scan in, card-driven
decode, SQLite timeseries store, MCP endpoint out, deterministic edge rules,
cloud-loop agent orchestration.

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
| `downsample` | roll old raw rows into aggregates (eMMC-friendly) |
| `smoke` | self-test of the whole pipeline |
| `relay on\|off [--seq N]` | prints the type-18 relay command frame to advertise from nRF Connect (the scanner is receive-only) |

## Layout (mirrors the architecture document)

```
gateway/
├── core.py                BLE payload spec (the one place the frame layout lives)
├── pipeline.py            scan -> dedupe -> decode -> reconcile -> store -> rules
├── scanner/   ble_scan.py (bleak), dedupe.py, sim_source.py (14-SIM simulator)
├── decoder/   registry.py (cards -> parsers), reconcile.py (seq loss, tick alignment)
├── store/     db.py (SQLite WAL), downsample.py
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
4. **Storage:** on the Uno Q keep the WAL store on eMMC but schedule
   `python -m gateway downsample` daily (cron) to bound writes; on a Pi with
   an SD card do the same.
5. **Service:** run `python -m gateway run` under systemd; run `mcp` on
   demand or expose it via an SSE transport if the cloud loop connects
   remotely.

Nothing in the pipeline imports Windows-only or Linux-only modules; the smoke
test is the porting acceptance test: if `python -m gateway smoke` passes on
the target, the gateway works there.
