@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0backend\scripts\restart_server.ps1"
if errorlevel 1 (
  echo.
  echo Orbit restart failed. See runtime\server.log for details.
  pause
  exit /b 1
)
echo Orbit backend and signal scanner restarted successfully.
echo Signal scanner log: runtime\signal-service.log
