function Get-OrbitPython {
    param([Parameter(Mandatory = $true)][string]$ProjectRoot)

    if ($env:PYTHON_BIN) {
        return $env:PYTHON_BIN
    }

    $VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (Test-Path $VenvPython) {
        return $VenvPython
    }

    $Command = Get-Command python -ErrorAction SilentlyContinue
    if (-not $Command) {
        throw "Python was not found. Install Python 3 or set PYTHON_BIN."
    }
    return $Command.Source
}
