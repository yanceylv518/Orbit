# Orbit Backend

后端工程目录，包含 Python 服务端、数据库脚本、运维脚本和单元测试。

```text
backend/
  main.py
  src/orbit/
  scripts/
  sql/
  tests/
```

本地启动：

```powershell
python backend/main.py
```

Codex bundled Python：

```powershell
& "C:\Users\Yancey\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" backend/main.py
```

MySQL 模式启动：

```powershell
.\backend\scripts\run_server_mysql.ps1
```

运行测试：

```powershell
python -m unittest discover -s backend/tests
```

Codex bundled Python：

```powershell
& "C:\Users\Yancey\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m unittest discover -s backend\tests
```
