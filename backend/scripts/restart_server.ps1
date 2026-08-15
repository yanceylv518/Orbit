$ErrorActionPreference = "Stop"

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendRoot = Split-Path -Parent $ScriptRoot
$ProjectRoot = Split-Path -Parent $BackendRoot
$ServerScript = Join-Path $ScriptRoot "run_server.ps1"
$Port = 8765

Write-Host "[Orbit] Checking port $Port..."
$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
    $commandLine = [string]$process.CommandLine
    if ($process.Name -notlike "python*.exe" -or $commandLine -notmatch "backend[\\/]main\.py") {
        throw "Port $Port is occupied by a non-Orbit process (PID $($listener.OwningProcess)); refusing to stop it."
    }
    $processSnapshot = Get-CimInstance Win32_Process
    function Get-OrbitDescendantIds([int]$ParentId) {
        $children = @($processSnapshot | Where-Object { $_.ParentProcessId -eq $ParentId })
        foreach ($child in $children) {
            Get-OrbitDescendantIds -ParentId $child.ProcessId
            $child.ProcessId
        }
    }
    $descendantIds = @(Get-OrbitDescendantIds -ParentId $listener.OwningProcess)
    Write-Host "[Orbit] Stopping old backend (PID $($listener.OwningProcess))..."
    if ($descendantIds.Count -gt 0) {
        Write-Host "[Orbit] Stopping $($descendantIds.Count) backend worker process(es)..."
        Stop-Process -Id $descendantIds -Force -ErrorAction SilentlyContinue
    }
    Stop-Process -Id $listener.OwningProcess -ErrorAction Stop
    $deadline = (Get-Date).AddSeconds(10)
    do {
        Start-Sleep -Milliseconds 250
        $stillListening = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    } while ($stillListening -and (Get-Date) -lt $deadline)
    if ($stillListening) {
        throw "Orbit backend did not release port $Port within 10 seconds."
    }
}

Write-Host "[Orbit] Starting backend..."
Start-Process `
    -FilePath "powershell.exe" `
    -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$ServerScript`"") `
    -WorkingDirectory $ProjectRoot `
    -WindowStyle Hidden

$healthUrl = "http://127.0.0.1:$Port/api/health"
$deadline = (Get-Date).AddSeconds(30)
do {
    Start-Sleep -Milliseconds 500
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $healthUrl -TimeoutSec 2
        if ($response.StatusCode -eq 200) {
            Write-Host "[Orbit] Backend is ready: $healthUrl" -ForegroundColor Green
            exit 0
        }
    } catch {
        # Startup can take a few seconds while dependencies and state are loaded.
    }
} while ((Get-Date) -lt $deadline)

$logPath = Join-Path $ProjectRoot "runtime\server.log"
throw "Orbit backend did not become healthy within 30 seconds. Check $logPath"
