"""Start file of aiot-gateway.exe (the Windows build, see BUILD.md).

Double-clicked, the .exe runs the gateway with real sensors (Bluetooth), the
dashboard and the MCP server together, in one window:

    aiot-gateway.exe                        real sensors
    aiot-gateway.exe --simulate             simulated sensors (Simulator.bat)
    aiot-gateway.exe --simulate --twin 1    any option of "gateway simulate"

Any other gateway command is passed through unchanged, against the same data
(add --simulate for the simulator's data):

    aiot-gateway.exe inject 1:1 spike
    aiot-gateway.exe tool read_latest 1:1
    aiot-gateway.exe tool read_latest 1:1 --simulate

Data is kept in a "data" folder next to the .exe, using the gateway's own
environment settings (nothing in gateway/ is specific to this build):

    data\\gateway.db      real sensors
    data\\simulated.db    simulator, so fake readings never mix with real ones
    data\\rules.d         approved rules and the deploy_rule token

The gateway code itself is unchanged; this file only sets those settings,
starts the MCP server next to the gateway and opens the dashboard.
"""

import os
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path


def app_folder():
    """The folder that holds the .exe (or the current folder, from source)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def pause_before_closing():
    """Keep the window open, so an error can be read before it closes."""
    print()
    try:
        input("Press Enter to close this window.")
    except (EOFError, KeyboardInterrupt):
        pass


def run_mcp_server():
    """The MCP server, in the background next to the gateway."""
    from gateway.__main__ import cmd_mcp
    try:
        cmd_mcp(None)
    except BaseException as exc:      # also SystemExit, e.g. port 8000 in use
        print(f"[mcp] the MCP server stopped: {exc!r}")
        print("[mcp] the gateway and dashboard keep running without it")


def open_dashboard():
    """Open the dashboard in the browser once the gateway has started."""
    time.sleep(3)
    webbrowser.open("http://localhost:8931")


def main():
    args = sys.argv[1:]
    data = app_folder() / "data"
    data.mkdir(exist_ok=True)

    # --simulate picks the simulator's data file; take it out of the list,
    # the gateway itself does not know this option
    simulate = "--simulate" in args
    options = []
    for option in args:
        if option != "--simulate":
            options.append(option)

    # A gateway command passed through (e.g. "tool read_latest 1:1"), or
    # nothing / only options: start the gateway and the MCP server
    passthrough = len(options) > 0 and not options[0].startswith("-")
    # --help alone: the gateway's list of all commands
    if options == ["--help"] or options == ["-h"]:
        passthrough = True

    # The gateway's settings, for this machine (see the docstring above)
    os.environ["GATEWAY_STORE_BACKEND"] = "sqlite"
    if simulate:
        os.environ["GATEWAY_DB_PATH"] = str(data / "simulated.db")
    else:
        os.environ["GATEWAY_DB_PATH"] = str(data / "gateway.db")
    os.environ["GATEWAY_RULES_DIR"] = str(data / "rules.d")

    from gateway.__main__ import main as gateway_main

    if passthrough:
        sys.argv = ["gateway"] + options
        gateway_main()
        return

    if simulate:
        sys.argv = ["gateway", "simulate"] + options
        mode = "SIMULATOR (no sensors needed)"
    else:
        sys.argv = ["gateway", "run"] + options
        mode = "REAL SENSORS (Bluetooth)"

    # The window title. "title" is a built-in of the Windows console; the
    # text is one of the two fixed strings above, never user input.
    if os.name == "nt":
        os.system(f"title AIoT Gateway - {mode}")
    print("=" * 60)
    print(f" AIoT Gateway - {mode}")
    print(f" Dashboard:  http://localhost:8931")
    print(f" MCP server: http://localhost:8000/mcp")
    print(f" Data file:  {os.environ['GATEWAY_DB_PATH']}")
    print(" Close this window (or press Ctrl+C) to stop.")
    print("=" * 60, flush=True)     # show this before the servers' own lines

    threading.Thread(target=run_mcp_server, daemon=True).start()
    threading.Thread(target=open_dashboard, daemon=True).start()
    gateway_main()


if __name__ == "__main__":
    try:
        main()
    except SystemExit as exc:
        # sys.exit() with an error (a message or a non-zero code)
        if exc.code not in (None, 0):
            if not isinstance(exc.code, int):
                print(exc.code)
            pause_before_closing()
        raise
    except KeyboardInterrupt:
        pass
    except BaseException:
        traceback.print_exc()
        pause_before_closing()
        sys.exit(1)
