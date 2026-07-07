@echo off
setlocal
set PYTHON=C:\Users\Yancey\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe
"%PYTHON%" "%~dp0configure_binance_account.py" %*
