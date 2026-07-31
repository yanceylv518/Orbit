# Orbit — 加密量化交易平台

Orbit 是一个自用的加密量化交易平台，当前形态包含四块核心能力：

1. **策略研究平台**：预注册冻结、锁箱一次性开启、结果只追加、verdict 对固定门槛的可审计研究流水线（候选墓地含双网格、Funding carry 等已证伪方向）。
2. **TB4 多周期趋势篮子**：唯一通过全部回测门（TB1→TB3→TB-R）的冻结策略——12 个 USDT 永续、4h、动量 `14/28/56/84/168` 天等权集成、vol28 定仓、目标波动 10%、7 天再平衡;paper 前向验证进行中（预注册 ≥12 个月）。
3. **LIVE-SMALL 小资金实盘**：与 paper 前向并行的 500 USDT 自动执行（冻结清单唯一指令源、逐单映射验证、哈希链账本、回撤 30% 机制停机、急停不对称）,协议见 `docs/design/LIVE_SMALL.md`。
4. **账户与治理**：业务用户/交易账户/凭证跨平台加密（Windows DPAPI / Linux AES-256-GCM）、Binance 只读同步、管理员审计。

> 项目早期名称为 “Dynamic Dual Grid V1”（双网格策略）;该策略经可行性判定全线 NO-GO 后归档,平台演进为上述形态。旧文档与产品方案中的双网格描述属历史记录。

## 目录结构

```text
backend/   Python 后端服务、应用分层、脚本、SQL、测试
frontend/  Vue 3 + Vite 前端控制台
docs/      产品方案、架构说明、策略逻辑设计和设计图
config/    配置样例；本地敏感配置仍使用根目录 config.local.json
```

## Windows 启动

建议创建项目虚拟环境并安装后端运行依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

运行后端测试时安装开发依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

首次启动前先构建前端：

```powershell
cd frontend
npm.cmd ci
npm.cmd run build
cd ..
```

```powershell
.\backend\scripts\run_server_mysql.cmd
```

启动后访问：

```text
http://127.0.0.1:8765
```

## Linux / VPS 启动

Ubuntu/Debian 需先安装 Python 3、venv、Node.js/npm 和 MySQL。仓库根目录执行：

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt

cd frontend
npm ci
npm run build
cd ..
```

Linux 保存 Binance API Key/Secret 时使用 AES-256-GCM。首次部署生成一次主密钥，并通过环境变量或服务器密钥管理服务注入：

```bash
export ORBIT_CREDENTIAL_MASTER_KEY="$(python backend/scripts/generate_vault_key.py)"
export DDG_MYSQL_PASSWORD="你的 MySQL 密码"
```

`ORBIT_CREDENTIAL_MASTER_KEY` 必须在每次重启时保持相同，不能提交到 Git，也不能在已经保存凭证后重新生成。密钥丢失后，旧密文无法恢复，只能重新录入账户凭证。

初始化数据库并以前台进程启动服务：

```bash
./backend/scripts/setup_mysql.sh
./backend/scripts/run_server_mysql.sh
```

服务启动后可在另一个终端检查：

```bash
./backend/scripts/healthcheck.sh
./backend/scripts/check_mysql.sh
```

仅使用 JSON fallback 时运行 `./backend/scripts/run_server.sh`。Git clone 会保留脚本执行权限；如果代码来自压缩包，可执行 `chmod +x backend/scripts/*.sh`。

## 登录

本地 JSON 开发模式可显式配置管理员 bootstrap 账号。MySQL/生产模式不接受
bootstrap 默认密码，必须先运行目录迁移并为管理员设置密码：

```bash
python backend/scripts/migrate_config_directory_to_mysql.py \
  --map-user user_001=你的业务用户ID \
  --set-admin-password
```

管理员密码后续可独立修改：

```powershell
.\backend\scripts\set_user_password.cmd admin_001
```

本系统控制台的使用者只有管理员：管理员登录后运行整个平台，维护业务用户与交易账户，并把平台提供的策略挂到账户上运行。业务用户只是交易账户的归属方（提供 Binance API Key/Secret），不登录控制台，不设计、不维护、也不运行策略。`set_user_password.py` 会拒绝为业务用户设置控制台密码。

## 项目文档

```text
docs/product/Dynamic Dual Grid V1 开发需求.pdf
docs/product/Dynamic Dual Grid V1 修正版产品技术方案.md
docs/design/ARCHITECTURE.md
docs/design/STRATEGY_LOGIC.md
docs/design/dynamic-dual-grid-product-design-cn.png
```

配置样例在：

```text
config/config.sample.json
```

## MySQL

建表脚本在：

```text
backend/sql/schema.sql
```

当前环境未安装 Python MySQL 驱动或未切换配置时，程序会自动使用本地 JSON 状态文件作为 dry_run fallback：

```text
var/data/runtime_state.json
```

### 接入步骤

1. 安装 MySQL 驱动：

```powershell
.\.venv\Scripts\python.exe -m pip install PyMySQL
```

2. 执行建库建表。脚本会读取 `DDG_MYSQL_PASSWORD`；如果没有设置，并且你在交互式 PowerShell 中运行，它会安全提示输入密码：

```powershell
.\backend\scripts\setup_mysql.cmd
```

也可以直接运行包装器：

```powershell
.\backend\scripts\setup_mysql.cmd
```

也可以只在当前 PowerShell 会话设置环境变量：

```powershell
$env:DDG_MYSQL_PASSWORD = "你的 MySQL root 密码"
```

不要把密码写入仓库文件。

3. 切换本地配置到 MySQL：

```powershell
.\.venv\Scripts\python.exe backend/scripts/use_mysql_storage.py
```

这会生成或更新：

```text
config.local.json
```

如果要把数据库用户名和密码写入本地配置，可运行：

```powershell
.\.venv\Scripts\python.exe backend/scripts/configure_mysql.py
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
.\backend\scripts\run_server_mysql.ps1
```

如果 PowerShell 执行策略禁止 `.ps1`，运行：

```powershell
.\backend\scripts\run_server_mysql.cmd
```

5. 启动服务后检查写入：

```powershell
.\backend\scripts\check_mysql.cmd
```

或者：

```powershell
.\backend\scripts\check_mysql.cmd
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

MySQL 模式下，数据库是 `users`、`exchange_accounts`、`strategy_instances` 和
`account_run_configs` 的唯一运行时来源。首次部署或旧部署升级时必须先运行
`migrate_config_directory_to_mysql.py`；该命令幂等迁移种子目录并保留现有密码哈希。
目录不完整或没有有效管理员时，Orbit 会拒绝启动，不会回退到
`config.local.json`。该文件在 MySQL 模式下只负责数据库连接、服务监听、账本路径和运行开关。

## Binance Futures 账户接入与受控实盘

账户默认只读同步。只有管理员在“实盘 → 小资金实盘启用向导”完成冻结前向初始化、规则刷新、
账户准备、生产预检和双重确认后，LIVE-SMALL 才会打开真实自动下单。

支持：

```text
GET /fapi/v3/account
GET /fapi/v3/positionRisk
GET /fapi/v1/positionSide/dual
POST /fapi/v1/order/test
```

数据库只保存 API Key/Secret 的环境变量引用或加密引用以及 API Key 指纹，不保存 Secret 明文。Windows 默认使用当前用户 DPAPI，Linux 默认使用由 `ORBIT_CREDENTIAL_MASTER_KEY` 驱动的 AES-256-GCM；也可以继续使用 `env:` 引用。

在当前 PowerShell 会话设置 Binance API 环境变量：

```powershell
$env:BINANCE_API_KEY = "你的 Binance Futures API Key"
$env:BINANCE_API_SECRET = "你的 Binance Futures API Secret"
```

把账户配置写入 MySQL：

```powershell
.\backend\scripts\configure_binance_account.cmd --user-id user_001 --account-id binance_testnet_001 --label "Binance Futures Testnet" --api-key-env BINANCE_API_KEY --secret-env BINANCE_API_SECRET --testnet true --dry-run true --attach-strategy orbit_v1_demo
```

参数说明：

```text
--testnet true   使用 Binance Futures demo-fapi
--testnet false  使用 Binance Futures 正式 fapi
--dry-run true   策略不执行真实下单
--dry-run false  允许该账户进入实盘预检，但本身不会启用自动下单
```

配置完成后登录页面，进入“账户”同步 Binance，即可读取真实余额、持仓和 Hedge Mode 状态。
需要启动 LIVE-SMALL 时，进入“实盘”的启用向导；运行控制持久化在 MySQL
`app_runtime_state`，不需要修改配置文件、运行策略脚本或重启服务。详细状态机和接口边界见
`docs/design/LIVE_PILOT_CONSOLE.md`。

## 验证

Windows PowerShell：

```powershell
python -m unittest discover -s backend/tests
cd frontend
npm.cmd run check
npm.cmd run build
```

Linux 可运行一体化验证脚本；该脚本会使用 `npm ci` 按锁文件安装前端依赖：

```bash
./backend/scripts/verify.sh
```

只验证后端时运行 `BACKEND_ONLY=1 ./backend/scripts/verify.sh`。

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
