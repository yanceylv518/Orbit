@echo off
setlocal
for %%I in ("%~dp0..") do set "BACKEND_ROOT=%%~fI"
for %%I in ("%BACKEND_ROOT%\..") do set "PROJECT_ROOT=%%~fI"

if defined PYTHON_BIN (
  set "ORBIT_PYTHON=%PYTHON_BIN%"
) else if exist "%PROJECT_ROOT%\.venv\Scripts\python.exe" (
  set "ORBIT_PYTHON=%PROJECT_ROOT%\.venv\Scripts\python.exe"
) else (
  set "ORBIT_PYTHON=python"
)

"%ORBIT_PYTHON%" %*
exit /b %ERRORLEVEL%
