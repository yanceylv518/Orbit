$ErrorActionPreference = "Stop"
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendRoot = Split-Path -Parent $ScriptRoot
$ProjectRoot = Split-Path -Parent $BackendRoot
Set-Location $ProjectRoot
New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot "runtime") | Out-Null
& "C:\Users\Yancey\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" (Join-Path $BackendRoot "main.py") *> (Join-Path $ProjectRoot "runtime\server.log")
