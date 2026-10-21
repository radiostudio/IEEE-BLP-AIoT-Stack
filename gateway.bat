@echo off
rem Runs any gateway command through the environment setup.bat built, with no
rem manual "activate" step. Example: gateway.bat simulate

set "SCRIPT_DIR=%~dp0"
set "VENV_PY=%SCRIPT_DIR%.venv-gateway\Scripts\python.exe"

if not exist "%VENV_PY%" (
    echo The gateway isn't set up yet. Run this first:
    echo   setup.bat
    exit /b 1
)

"%VENV_PY%" -m gateway %*
exit /b %errorlevel%
