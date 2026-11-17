AIoT Gateway for Windows
========================

This program receives the readings of the AIoT sensor nodes over Bluetooth,
saves them, and shows them on a web page (the dashboard). It also runs an
MCP server, so an AI assistant can read the sensor data.

Nothing to install: everything is in this folder.


1. Before you start
-------------------

- Unzip the whole folder first (right-click the zip, "Extract All...").
  Do not run the program from inside the zip.
- Switch Bluetooth on: Settings > Bluetooth & devices > Bluetooth: On.
- Power your sensor nodes.


2. Start it
-----------

Real sensors:      double-click  aiot-gateway.exe
No sensors?        double-click  Simulator.bat   (simulated sensors)

A black window opens and the dashboard opens in your browser:

    http://localhost:8931

The first time, Windows may ask two things:

- "Windows protected your PC": click "More info", then "Run anyway".
  (The program is not signed by a company; it is safe to run.)
- "Windows Defender Firewall has blocked some features": tick
  "Private networks" and click "Allow access".

Your sensors appear on the dashboard within a few seconds of being heard.
The black window shows what the gateway receives.


3. Stop it
----------

Close the black window, or click in it and press Ctrl+C.


4. Where your data is
---------------------

In the "data" folder next to aiot-gateway.exe:

    data\gateway.db       readings of your real sensors
    data\simulated.db     readings of the simulator

The data stays there when you close the program. To start from empty,
close the program and delete the file.


5. The MCP server
-----------------

Runs together with the gateway, at:

    http://localhost:8000/mcp


6. Commands (optional)
----------------------

Open a Command Prompt in this folder (click the address bar of the folder,
type cmd, press Enter), then for example:

    aiot-gateway.exe --simulate --fault 1:spike    simulator with a temperature spike
    aiot-gateway.exe --simulate --twin 1           two simulated temperature sensors
    aiot-gateway.exe tool read_latest 1:1          latest reading of sensor 1:1
    aiot-gateway.exe --help                        all commands (most are for instructors)


7. If something goes wrong
--------------------------

The window closes at once
    Start it from a Command Prompt (see 6) to read the message.

"Press Enter to close this window." with an error above it
    Read the error; often one of the cases below.

No sensors on the dashboard
    Is Bluetooth on? Are the nodes powered and close by? Try Simulator.bat:
    if the simulated sensors show, the program works and the problem is
    Bluetooth or the nodes.

Windows Security / antivirus removed or blocked aiot-gateway.exe
    Ask your instructor.

The dashboard does not open
    Open http://localhost:8931 in your browser yourself. If the gateway
    window says a different port (e.g. 8932), use that one: another program
    was already using 8931.

"[actuator] searching: actuator not found"
    Normal without the relay actuator; the gateway works without it. With
    the actuator: is its USB cable plugged in, and does Device Manager show
    it under "Ports (COM & LPT)"? Close the Arduino IDE's Serial Monitor or
    any other program using that COM port.

"[mcp] the MCP server stopped"
    Another program uses port 8000, or the gateway is already running in
    another window. The dashboard keeps working; close the other window.
