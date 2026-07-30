$ErrorActionPreference = "Stop"
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendRoot = Split-Path -Parent $ScriptRoot
$ProjectRoot = Split-Path -Parent $BackendRoot
Set-Location $ProjectRoot

. (Join-Path $ScriptRoot "resolve_python.ps1")
$Python = Get-OrbitPython -ProjectRoot $ProjectRoot

& $Python (Join-Path $ScriptRoot "use_mysql_storage.py")
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
& $Python (Join-Path $BackendRoot "main.py")
