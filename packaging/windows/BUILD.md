# Windows build for students

`aiot-gateway.exe`: the gateway, its dashboard and the MCP server in one
program, with SQLite storage. Students unzip it and double-click; no Python,
no Docker, no InfluxDB.

| Double-click | Runs | Data file |
|---|---|---|
| `aiot-gateway.exe` | real sensors over the laptop's Bluetooth | `data\gateway.db` |
| `Simulator.bat` | the gateway's simulator, no sensors needed | `data\simulated.db` |

Dashboard `http://localhost:8931`, MCP server `http://localhost:8000/mcp`.
The `data` folder is created next to the .exe.

## Why not Docker on Windows

Docker Desktop runs containers in a Linux virtual machine (WSL2) that cannot
use the laptop's Bluetooth adapter: only the simulator would work. It also
needs WSL2, virtualization switched on in the BIOS and admin rights.

## Files

| File | What it is |
|---|---|
| `entry.py` | The start file of the .exe. Sets the gateway's settings (`GATEWAY_STORE_BACKEND=sqlite`, `GATEWAY_DB_PATH`, `GATEWAY_RULES_DIR`) to the `data` folder, starts the MCP server next to the gateway, opens the dashboard. Other commands pass through: `aiot-gateway.exe tool read_latest 1:1`. On an error it waits for Enter, so the window does not vanish |
| `aiot_gateway.spec` | The PyInstaller recipe: a folder build with the cards, dashboard page, MCP prompts and resources, agent recipes, and the Bluetooth (WinRT) and MCP packages |
| `build_windows.bat` | Builds everything and makes the zip |
| `Simulator.bat` | Copied into the zip: `aiot-gateway.exe --simulate` |
| `README.txt` | Copied into the zip: the students' instructions |

The gateway code is the same as for `gateway.bat`, the Uno Q and Docker.

## Build

On a Windows PC with Python 3.12 or newer (python.org, "Add python.exe to
PATH" checked) and this repository:

```
packaging\windows\build_windows.bat
```

It creates `.venv-build` (only `gateway\requirements.txt` and PyInstaller,
so no pandas or Jupyter), builds, and writes:

```
build\windows\AIoT-Gateway-Windows.zip      <- hand this out
build\windows\dist\AIoT-Gateway\            the same, unzipped
```

`build\` and `.venv-build\` are not in git. Build again after any change to
the gateway or the cards; there is no other way to update a student's copy.

The build is for the Windows version and processor it is built on: build
on a 64-bit Windows 10 or 11 PC for ordinary laptops.

### A folder, not a single .exe

PyInstaller can also make one single .exe (`--onefile`); this build does
not, on purpose:

- A single file unpacks itself into a new temporary folder at every start.
  The gateway keeps `faults.json` (used by `inject`) and the agents'
  evidence packs inside its own folder, so they would be lost, and
  `aiot-gateway.exe inject ...` would never reach the running gateway.
- Antivirus programs flag single-file PyInstaller programs more often.
- It starts in 5 to 10 s instead of about 1 s.

## Check before handing out

On a Windows laptop with built-in Bluetooth, from the zip, unzipped into a
new folder (e.g. the Desktop):

1. Double-click `Simulator.bat`. The window title and first lines say
   `SIMULATOR`, the dashboard opens and shows 14 sensors within a few
   seconds; the firewall question appears once.
2. Close the window. `data\simulated.db` exists.
3. With Bluetooth on and a sensor node powered, double-click
   `aiot-gateway.exe`. The window says `REAL SENSORS`; the node appears in
   the window (`... online: ...`) and on the dashboard.
4. MCP: in a Command Prompt in the folder,
   `curl -s -o NUL -w "%{http_code}" http://localhost:8000/mcp` prints a
   number (e.g. `406`): the server answers. Or connect an MCP client to
   `http://localhost:8000/mcp`.
5. `aiot-gateway.exe tool read_latest 1:1` (with the gateway running or
   not) prints the stored reading of sensor 1:1 from `data\gateway.db`.
6. Close and start again: the earlier readings are still on the dashboard
   (History tab).
7. Switch Bluetooth off and double-click `aiot-gateway.exe`: note what the
   window shows, for the students' troubleshooting.
8. Actuator (if you use one): plug the actuator's USB-serial adapter in;
   Device Manager shows it under "Ports (COM & LPT)" (a CH340 or CP210x
   adapter may need its driver first). Start `aiot-gateway.exe`: the window
   says `[actuator] connected on COM<n>`. Without an actuator it says
   `searching: actuator not found (...)` once, and again only when a port
   is plugged in or out.
9. Start it twice: the second window should say `[mcp] the MCP server
   stopped`, and its dashboard moves to port 8932.

If Windows Security removes the .exe on a student laptop: building again
with a newer PyInstaller often helps; otherwise students use `setup.bat`
and `gateway.bat` (needs Python).

## What was tested where

On Linux: the same recipe built into a Linux binary; the simulator, the
dashboard (`/api/sensors` and the page), the MCP server (tools listed,
`read_latest` answered), the `data` folder next to the binary, separate
simulator and real files, pass-through commands, and a clean stop with
Ctrl+C. The actuator link with a simulated actuator on a virtual serial
port (connect, relay on and off, one search line), and the Windows port
filter with a made-up port list. Not tested on Linux: Windows Bluetooth
(WinRT), a real COM port, the .bat files, the zip, SmartScreen and the
firewall question: use the checklist above.
