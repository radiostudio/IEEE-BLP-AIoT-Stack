@echo off
setlocal

rem Builds the Windows gateway for students: build\windows\AIoT-Gateway-Windows.zip
rem Run on a Windows PC with Python 3.12 or newer, from any folder:
rem
rem   packaging\windows\build_windows.bat
rem
rem See packaging\windows\BUILD.md. Safe to run again: it rebuilds everything.

rem The repository root, two folders up from this file
cd /d "%~dp0..\.."
set "ROOT=%CD%"
set "OUT=%ROOT%\build\windows"
set "VENV=%ROOT%\.venv-build"

echo == AIoT Gateway: Windows build ==
echo.

rem 1. Python
set "PYCMD="
where py >nul 2>nul
if %errorlevel%==0 set "PYCMD=py -3"
if not defined PYCMD (
    where python >nul 2>nul
    if not errorlevel 1 set "PYCMD=python"
)
if not defined PYCMD goto no_python

rem 2. A separate build environment with only what the gateway needs
if not exist "%VENV%\Scripts\python.exe" (
    echo Creating the build environment in .venv-build ...
    %PYCMD% -m venv "%VENV%"
    if errorlevel 1 goto failed
)
echo Installing the gateway's packages and PyInstaller ...
"%VENV%\Scripts\python.exe" -m pip install --quiet --upgrade pip
"%VENV%\Scripts\python.exe" -m pip install --quiet -r gateway\requirements.txt pyinstaller==6.22.3
if errorlevel 1 goto failed

rem 3. Build
echo Building aiot-gateway.exe ...
if exist "%OUT%" rmdir /s /q "%OUT%"
"%VENV%\Scripts\pyinstaller.exe" --noconfirm --clean --distpath "%OUT%\dist" --workpath "%OUT%\work" packaging\windows\aiot_gateway.spec
if errorlevel 1 goto failed

rem 4. The students' folder: the program, Simulator.bat and README.txt
set "APP=%OUT%\dist\AIoT-Gateway"
move "%OUT%\dist\aiot-gateway" "%APP%" >nul
copy /y packaging\windows\Simulator.bat "%APP%\" >nul
copy /y packaging\windows\README.txt "%APP%\" >nul

rem 5. The zip to hand out
echo Making the zip ...
powershell -NoProfile -Command "Compress-Archive -Path '%APP%' -DestinationPath '%OUT%\AIoT-Gateway-Windows.zip' -Force"
if errorlevel 1 goto failed

echo.
echo Done: %OUT%\AIoT-Gateway-Windows.zip
echo Test it before handing it out: see "Check before handing out" in
echo packaging\windows\BUILD.md
exit /b 0

:no_python
echo No Python 3 found. Install Python 3.12 or newer from python.org,
echo with "Add python.exe to PATH" checked, then run this again.
exit /b 1

:failed
echo.
echo The build failed: see the messages above.
exit /b 1
