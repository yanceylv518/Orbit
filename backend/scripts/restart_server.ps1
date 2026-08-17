$ErrorActionPreference = "Stop"

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendRoot = Split-Path -Parent $ScriptRoot
$ProjectRoot = Split-Path -Parent $BackendRoot
$ServerScript = Join-Path $ScriptRoot "run_server.ps1"
$SignalScript = Join-Path $BackendRoot "tools\run_sig1_signal_service.py"
$RuntimeRoot = Join-Path $ProjectRoot "runtime"
$SignalPidPath = Join-Path $RuntimeRoot "signal-service.pid"
$SignalLogPath = Join-Path $RuntimeRoot "signal-service.log"
$SignalErrorPath = Join-Path $RuntimeRoot "signal-service.err"
$Port = 8765
New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null

. (Join-Path $ScriptRoot "resolve_python.ps1")
$Python = Get-OrbitPython -ProjectRoot $ProjectRoot

function Stop-OrbitSignalService {
    $candidateIds = @()
    if (Test-Path $SignalPidPath) {
        $storedPid = 0
        if ([int]::TryParse((Get-Content $SignalPidPath -Raw).Trim(), [ref]$storedPid)) {
            $candidateIds += $storedPid
        }
    }
    $escapedScript = [regex]::Escape($SignalScript)
    $candidateIds += @(
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object { [string]$_.CommandLine -match $escapedScript } |
            Select-Object -ExpandProperty ProcessId
    )
    foreach ($processId in @($candidateIds | Sort-Object -Unique)) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$processId" -ErrorAction SilentlyContinue
        if (-not $process) { continue }
        if ([string]$process.CommandLine -notmatch $escapedScript) {
            throw "PID $processId from signal-service.pid is not the Orbit signal scanner; refusing to stop it."
        }
        Write-Host "[Orbit] Stopping old signal scanner (PID $processId)..."
        Stop-Process -Id $processId -ErrorAction Stop
        Wait-Process -Id $processId -Timeout 10 -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $SignalPidPath -Force -ErrorAction SilentlyContinue
}

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

Stop-OrbitSignalService

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
            break
        }
    } catch {
        # Startup can take a few seconds while dependencies and state are loaded.
    }
} while ((Get-Date) -lt $deadline)

$logPath = Join-Path $ProjectRoot "runtime\server.log"
if (-not $response -or $response.StatusCode -ne 200) {
    throw "Orbit backend did not become healthy within 30 seconds. Check $logPath"
}

Write-Host "[Orbit] Starting SIG-1 signal scanner..."
$signalProcess = Start-Process `
    -FilePath $Python `
    -ArgumentList @("`"$SignalScript`"", "--loop") `
    -WorkingDirectory $ProjectRoot `
    -RedirectStandardOutput $SignalLogPath `
    -RedirectStandardError $SignalErrorPath `
    -WindowStyle Hidden `
    -PassThru
Set-Content -LiteralPath $SignalPidPath -Value $signalProcess.Id -Encoding ascii

Start-Sleep -Seconds 2
$signalProcess.Refresh()
if ($signalProcess.HasExited) {
    Remove-Item -LiteralPath $SignalPidPath -Force -ErrorAction SilentlyContinue
    throw "Orbit signal scanner exited during startup. Check $SignalErrorPath"
}

Write-Host "[Orbit] Signal scanner is running (PID $($signalProcess.Id))." -ForegroundColor Green
Write-Host "[Orbit] Logs: $SignalLogPath"
Write-Host "[Orbit] The scanner respects the service switch in the Signal page; first scan may take several minutes."
exit 0
