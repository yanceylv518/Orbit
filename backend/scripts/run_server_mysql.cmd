@echo off
setlocal
for %%I in ("%~dp0..") do set BACKEND_ROOT=%%~fI
for %%I in ("%BACKEND_ROOT%\..") do set PROJECT_ROOT=%%~fI
cd /d "%PROJECT_ROOT%"
C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_server_mysql.ps1"
