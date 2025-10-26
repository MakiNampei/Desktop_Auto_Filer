@echo off
setlocal enableextensions
cd /d "%~dp0"

set "VENV=.venv"
set "PYEX=%VENV%\Scripts\python.exe"
set "PIP=%VENV%\Scripts\pip.exe"
set NO_PROXY=127.0.0.1,localhost
set no_proxy=127.0.0.1,localhost


if not exist "%PYEX%" (
  echo [Setup] Creating virtual environment...
  py -3.11 -m venv "%VENV%" || py -3 -m venv "%VENV%" || py -m venv "%VENV%" || goto :python_missing
)

echo [Setup] Ensuring UI deps...
"%PYEX%" -m pip install --upgrade pip >nul
"%PIP%" install PySide6 watchdog

echo [Run] Launching UI...
start "" "%PYEX%" ui.py
exit /b 0

:python_missing
echo [Error] Python launcher not found. Install Python 3.11+ and ensure 'py' works.
pause
exit /b 1
