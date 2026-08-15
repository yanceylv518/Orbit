$ErrorActionPreference = "Stop"
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendRoot = Split-Path -Parent $ScriptRoot
$ProjectRoot = Split-Path -Parent $BackendRoot
Set-Location $ProjectRoot
New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot "runtime") | Out-Null

. (Join-Path $ScriptRoot "resolve_python.ps1")
$Python = Get-OrbitPython -ProjectRoot $ProjectRoot
$LogPath = Join-Path $ProjectRoot "runtime\server.log"

# Uvicorn writes normal lifecycle messages to stderr. Windows PowerShell turns
# native stderr into error records when ErrorActionPreference is Stop, which
# previously terminated an otherwise healthy server during startup.
$ErrorActionPreference = "Continue"
& $Python (Join-Path $BackendRoot "main.py") *> $LogPath
exit $LASTEXITCODE
