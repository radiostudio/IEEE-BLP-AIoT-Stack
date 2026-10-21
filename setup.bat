@echo off
setlocal enabledelayedexpansion

rem Full gateway setup for Windows. Safe to run more than once.
rem Options: --recreate (rebuild the environment from scratch)
rem          --with-anthropic (also install the extra package for BYOK students)
rem          --with-pptx (also install python-pptx, needed only to regenerate
rem                       slides from sensor_decks/ via tools/md2pptx.py -
rem                       instructors/content authors only, not needed by students)

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

set "RECREATE=0"
set "WITH_ANTHROPIC=0"
set "WITH_PPTX=0"
for %%A in (%*) do (
    if /I "%%~A"=="--recreate" set "RECREATE=1"
    if /I "%%~A"=="--with-anthropic" set "WITH_ANTHROPIC=1"
    if /I "%%~A"=="--with-pptx" set "WITH_PPTX=1"
)

echo == AIoT Gateway setup (Windows) ==
echo.

rem 1. Find a Python 3 interpreter (Python Launcher first, then plain python).
rem The Python snippets below are kept in variables, not written directly
rem inside the if (...) blocks - Windows batch counts parentheses in the raw
rem script text to find where a block ends, and gets confused by the
rem parentheses that are just a normal part of this Python code (e.g. the
rem parentheses in "sys.exit(...)"), even though they're inside quotes.
rem Same reason: never write a literal, unquoted "(" or ")" as plain text
rem (e.g. in an echo message) inside an if (...) block - reword the message
rem instead, or the block-parsing breaks the same way.
set "PYCMD="
set "PY_CHECK_IS3=import sys; sys.exit(0 if sys.version_info[0]==3 else 1)"

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 -c "import sys" >nul 2>nul
    if !errorlevel!==0 set "PYCMD=py -3"
)

if not defined PYCMD (
    where python >nul 2>nul
    if %errorlevel%==0 (
        python -c "!PY_CHECK_IS3!" >nul 2>nul
        if !errorlevel!==0 set "PYCMD=python"
    )
)

if not defined PYCMD (
    echo No Python 3 installation was found on this machine.
    echo Install Python 3.10 or newer from https://www.python.org/downloads/windows/
    echo IMPORTANT: check "Add python.exe to PATH" during install.
    echo.
    echo If this is a school/managed laptop and you cannot install software,
    echo ask your instructor for help.
    exit /b 1
)

rem 2. Check the version is at least 3.10.
set "PY_CHECK_310=import sys; sys.exit(0 if sys.version_info[:2] >= (3, 10) else 1)"
set "PY_PRINT_VERSION=import platform; print(platform.python_version())"
%PYCMD% -c "!PY_CHECK_310!"
if not !errorlevel!==0 (
    for /f "delims=" %%V in ('%PYCMD% -c "!PY_PRINT_VERSION!"') do set "DETECTED=%%V"
    echo Detected Python !DETECTED!, but the gateway needs Python 3.10 or newer.
    echo Install a newer Python: https://www.python.org/downloads/
    exit /b 2
)

rem 3. Create or reuse the virtual environment.
set "VENV_DIR=%SCRIPT_DIR%.venv-gateway"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"

if "%RECREATE%"=="1" (
    if exist "%VENV_DIR%" (
        echo Removing existing .venv-gateway, since --recreate was passed...
        rmdir /s /q "%VENV_DIR%"
    )
)

set "VENV_OK=0"
if exist "%VENV_PY%" (
    "%VENV_PY%" -c "import sys" >nul 2>nul
    if !errorlevel!==0 set "VENV_OK=1"
)

if "%VENV_OK%"=="1" (
    echo Reusing existing .venv-gateway.
) else (
    if exist "%VENV_DIR%" (
        echo Existing .venv-gateway looks broken, rebuilding it...
        rmdir /s /q "%VENV_DIR%"
    )
    echo Creating .venv-gateway...
    %PYCMD% -m venv "%VENV_DIR%"
    if not !errorlevel!==0 (
        echo.
        echo Could not create a virtual environment.
        echo If you don't have permission to install software, ask your instructor for help.
        exit /b 3
    )
)

rem 4. Upgrade pip (best-effort, never fatal).
"%VENV_PY%" -m pip install --upgrade pip >nul 2>nul

rem 5. Install dependencies.
echo Installing gateway dependencies...
"%VENV_PY%" -m pip install -r "%SCRIPT_DIR%gateway\requirements.txt"
if not !errorlevel!==0 (
    echo.
    echo Could not install the required packages.
    echo Check your Wi-Fi connection and that you have free disk space, then try
    echo this command by hand:
    echo   "%VENV_PY%" -m pip install -r gateway\requirements.txt
    exit /b 4
)

if "%WITH_ANTHROPIC%"=="1" (
    echo Installing the anthropic package, since --with-anthropic was passed...
    "%VENV_PY%" -m pip install "anthropic>=0.40"
)

if "%WITH_PPTX%"=="1" (
    echo Installing python-pptx, since --with-pptx was passed...
    "%VENV_PY%" -m pip install "python-pptx>=0.6"
)

rem 6. Run the existing pass/fail test.
echo.
echo Running the gateway self-test (python -m gateway smoke)...
"%VENV_PY%" -m gateway smoke
set "SMOKE_STATUS=%errorlevel%"

if not "%SMOKE_STATUS%"=="0" (
    echo.
    echo Setup finished, but the self-test failed.
    echo Copy the output above and show it to your instructor.
    exit /b %SMOKE_STATUS%
)

rem Windows doesn't need the Linux Bluetooth-permission step - bleak talks to
rem the Windows Bluetooth stack directly.

rem 7. Success.
echo.
echo Setup complete! Try:
echo   gateway.bat simulate
echo.
echo Before you use the gateway for real, that is python -m gateway run,
echo take a look at PREREQUISITES.md - it covers a couple of one-time,
echo one-per-machine things this script can't do for you, like turning
echo Bluetooth on.
exit /b 0
