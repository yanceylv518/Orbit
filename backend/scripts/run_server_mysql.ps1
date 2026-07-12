$ErrorActionPreference = "Stop"
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendRoot = Split-Path -Parent $ScriptRoot
$ProjectRoot = Split-Path -Parent $BackendRoot
Set-Location $ProjectRoot

& "C:\Users\Yancey\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" (Join-Path $ScriptRoot "use_mysql_storage.py")
& "C:\Users\Yancey\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" (Join-Path $BackendRoot "main.py")
