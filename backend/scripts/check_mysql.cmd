@echo off
setlocal
for %%I in ("%~dp0..") do set BACKEND_ROOT=%%~fI
for %%I in ("%BACKEND_ROOT%\..") do set PROJECT_ROOT=%%~fI
cd /d "%PROJECT_ROOT%"
"C:\Users\Yancey\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" "%~dp0check_mysql.py"
