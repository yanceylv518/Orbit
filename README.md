# Dynamic Dual Grid V1

第一版实现内容：

1. 中文 Web 控制台。
2. dry_run 模拟行情和模拟成交。
3. 利润搬运、仓位恢复、亏损腿减仓三类核心事件。
4. 用户、交易账户、策略实例、管理员风控中心的数据结构。
5. 事件参数在线编辑和管理员审计日志。
6. 运行状态持久化和重启恢复。
7. MySQL 建表脚本和配置入口。
8. 每日复盘报告 Markdown + SVG 曲线图。
9. 管理员用户/账户总览、全局急停和恢复运行。
10. 本地登录、用户会话、用户/账户权限隔离。

## 启动

```powershell
python main.py
```

如果要使用 Codex bundled Python：

```powershell
& "C:\Users\Yancey\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" main.py
```

启动后访问：

```text
http://127.0.0.1:8765
```

## 登录

本地开发默认账号：

```text
admin_001 / admin123456
user_001 / user123456
```

首次使用 MySQL 登录时，如果用户还没有密码哈希，系统会用上述本地开发密码完成一次初始化并写入 `users.password_hash`。实盘测试前必须修改密码：

```powershell
& "C:\Users\Yancey\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts/set_user_password.py admin_001
& "C:\Users\Yancey\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts/set_user_password.py user_001
```

本系统的使用者是管理员：管理员登录后运行整个平台，维护业务用户与交易账户，并把平台提供的策略挂到账户上运行。业务用户只是交易账户的归属方（提供 Binance API Key/Secret），不设计、不维护、也不运行策略。若开启登录，业务用户会话仅用于隔离数据可见范围，不承担任何策略操作职责。

## MySQL

建表脚本在：

```text
sql/schema.sql
```

当前环境未安装 Python MySQL 驱动或未切换配置时，程序会自动使用本地 JSON 状态文件作为 dry_run fallback：

```text
data/runtime_state.json
```

### 接入步骤

1. 安装 MySQL 驱动：

```powershell
& "C:\Users\Yancey\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m pip install PyMySQL
```

2. 执行建库建表。脚本会读取 `DDG_MYSQL_PASSWORD`；如果没有设置，并且你在交互式 PowerShell 中运行，它会安全提示输入密码：

```powershell
& "C:\Users\Yancey\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts/setup_mysql.py
```

也可以直接运行包装器：

```powershell
.\scripts\setup_mysql.cmd
```

也可以只在当前 PowerShell 会话设置环境变量：

```powershell
$env:DDG_MYSQL_PASSWORD = "你的 MySQL root 密码"
```

不要把密码写入仓库文件。

3. 切换本地配置到 MySQL：

```powershell
& "C:\Users\Yancey\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts/use_mysql_storage.py
```

这会生成或更新：

```text
config.local.json
```

如果要把数据库用户名和密码写入本地配置，可运行：

```powershell
& "C:\Users\Yancey\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts/configure_mysql.py
```

`config.local.json` 已加入 `.gitignore`，不会提交。

其中 storage 会变成：

```json
{
  "storage": {
    "driver": "mysql",
    "mysql": {
      "host": "127.0.0.1",
      "port": 3306,
      "database": "dynamic_dual_grid",
      "user": "root",
      "password_env": "DDG_MYSQL_PASSWORD"
    }
  }
}
```

4. 用 MySQL 模式启动服务：

```powershell
.\scripts\run_server_mysql.ps1
```

如果 PowerShell 执行策略禁止 `.ps1`，运行：

```powershell
.\scripts\run_server_mysql.cmd
```

5. 启动服务后检查写入：

```powershell
& "C:\Users\Yancey\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts/check_mysql.py
```

或者：

```powershell
.\scripts\check_mysql.cmd
```

MySQL store 会写入：

```text
users
exchange_accounts
strategy_instances
symbol_allocations
symbol_states
market_snapshots
strategy_events
trade_events
admin_audit_logs
daily_reports
app_runtime_state
```

MySQL 模式下，应用启动会优先从数据库的 `users`、`exchange_accounts`、`strategy_instances` 读取用户、账户和策略归属。`config.local.json` 只作为启动连接和种子配置，不再作为唯一业务配置源。

## Binance Futures 只读接入

第一版 Binance 接入只做真实账户只读同步和环境校验，不会真实下单。

支持：

```text
GET /fapi/v3/account
GET /fapi/v3/positionRisk
GET /fapi/v1/positionSide/dual
POST /fapi/v1/order/test
```

数据库只保存 API Key/Secret 的环境变量引用和 API Key 指纹，不保存 Secret 明文。

在当前 PowerShell 会话设置 Binance API 环境变量：

```powershell
$env:BINANCE_API_KEY = "你的 Binance Futures API Key"
$env:BINANCE_API_SECRET = "你的 Binance Futures API Secret"
```

把账户配置写入 MySQL：

```powershell
.\scripts\configure_binance_account.cmd --user-id user_001 --account-id binance_testnet_001 --label "Binance Futures Testnet" --api-key-env BINANCE_API_KEY --secret-env BINANCE_API_SECRET --testnet true --dry-run true --attach-strategy ddg_v1_demo
```

参数说明：

```text
--testnet true   使用 Binance Futures demo-fapi
--testnet false  使用 Binance Futures 正式 fapi
--dry-run true   策略不执行真实下单
--dry-run false  预留给后续实盘小额下单，当前版本仍默认不开放真实下单
```

配置完成后重启服务，登录页面后进入“用户账户”，点击“同步 Binance”即可读取真实余额、持仓和 Hedge Mode 状态。

## 核心策略

每个 tick 的优先级：

```text
1. 风控检查
2. 单边趋势确认后的亏损腿减仓
3. 利润搬运
4. 搬运后的仓位恢复
5. 写入状态和事件
```

第一版只做 dry_run，不会真实下单。
