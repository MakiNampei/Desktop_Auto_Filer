@echo off
setlocal enableextensions
cd /d "%~dp0"

set "VENV=.venv"
set "PYEX=%VENV%\Scripts\python.exe"
set "PYW=%VENV%\Scripts\pythonw.exe"
set "PIP=%VENV%\Scripts\pip.exe"
set "AGENT_URL=http://127.0.0.1:8000"
set "REQ=requirements.txt"
set "AGLOG=%LOCALAPPDATA%\DeskPilot\agent-run.log"
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
set NO_PROXY=127.0.0.1,localhost
set no_proxy=127.0.0.1,localhost


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

REM ---- sanity: print interpreter path so you know which Python is used
echo [Info] Using interpreter: "%PYEX%"

REM ---- start agent MINIMIZED and LOGGED (do NOT use pythonw.exe)
echo [Run] Launching agent (minimized) and logging to %AGLOG%
echo [%date% %time%] launching agent > "%AGLOG%"
start "" /min cmd /c ""%PYEX%" -u agent.py 1>>"%AGLOG%" 2>&1"

REM ---- wait for health (now instant since /health returns immediately)
echo [Run] Waiting for agent at %AGENT_URL%/health ...
set /a WAITED=0
:wait_loop
powershell -NoLogo -Command "try{Invoke-RestMethod '%AGENT_URL%/health' -TimeoutSec 1 | Out-Null; exit 0}catch{exit 1}"
if errorlevel 1 (
  set /a WAITED+=1
  if %WAITED% GEQ 180 (
    echo [Warn] Agent not ready after 180s. Check log: %AGLOG%
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
echo [Error] Python launcher not found. Install Python 3.11+ and ensure 'py' works.
pause
exit /b 1
