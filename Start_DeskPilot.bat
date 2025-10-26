@echo off
setlocal enableextensions
cd /d "%~dp0"

REM ---------- settings ----------
set "VENV=.venv"
set "PYEX=%VENV%\Scripts\python.exe"
set "PYW=%VENV%\Scripts\pythonw.exe"
set "PIP=%VENV%\Scripts\pip.exe"
set "AGENT_URL=http://127.0.0.1:8000"
set "REQ=requirements.txt"
set HF_HUB_DISABLE_SYMLINKS_WARNING=1

if /i "%~1"=="--rebuild" (
  if exist "%VENV%" rmdir /s /q "%VENV%"
)

if not exist "%PYEX%" (
  echo [Setup] Creating virtual environment...
  py -3.11 -m venv "%VENV%" || py -3 -m venv "%VENV%" || py -m venv "%VENV%" || goto :python_missing
)

echo [Setup] Ensuring dependencies...
"%PYEX%" -m pip install --upgrade pip >nul
if exist "%REQ%" (
  "%PIP%" install -r "%REQ%"
) else (
  "%PIP%" install uagents watchdog requests sentence-transformers numpy
)

echo [Run] Starting agent (hidden)...
start "" "%PYW%" agent.py

echo [Run] Waiting for agent at %AGENT_URL%/health ...
set /a WAITED=0
:wait_loop
powershell -NoLogo -Command "try{Invoke-RestMethod '%AGENT_URL%/health' -TimeoutSec 1 | Out-Null; exit 0}catch{exit 1}"
if errorlevel 1 (
  set /a WAITED+=1
  if %WAITED% GEQ 60 (
    echo [Warn] Agent not ready after 60s. It may still be starting.
    echo        If it never comes up, see: %%LOCALAPPDATA%%\DeskPilot\agent.log
    goto :start_controller
  )
  timeout /t 1 >nul
  goto :wait_loop
)

:start_controller
echo [Run] Starting controller...
start "DeskPilot Controller" "%PYEX%" controller.py
exit /b 0

:python_missing
echo [Error] Python launcher not found. Install Python 3.11+ from python.org
echo         and ensure the 'py' launcher is available.
pause
exit /b 1
