$ErrorActionPreference = "Stop"
Set-Location "D:\CodexProjects\Orbit"
& "C:\Users\Yancey\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" "D:\CodexProjects\Orbit\main.py" *> "D:\CodexProjects\Orbit\runtime\server.log"
