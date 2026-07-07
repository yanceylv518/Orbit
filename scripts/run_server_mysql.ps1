$ErrorActionPreference = "Stop"
Set-Location "D:\CodexProjects\Orbit"

& "C:\Users\Yancey\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" "D:\CodexProjects\Orbit\scripts\use_mysql_storage.py"
& "C:\Users\Yancey\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" "D:\CodexProjects\Orbit\main.py"
