@echo off
rem Starts the AIoT gateway with SIMULATED sensors: no sensor nodes and no
rem Bluetooth needed. The dashboard opens in your browser by itself.
rem
rem For the real sensors, double-click aiot-gateway.exe instead.
rem
rem The simulated readings are saved in data\simulated.db, separate from the
rem real ones in data\gateway.db.

rem Run from the folder this file is in, wherever it was unzipped
cd /d "%~dp0"

aiot-gateway.exe --simulate %*
