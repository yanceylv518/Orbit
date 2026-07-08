# Dynamic Dual Grid V1 项目进度

最后更新：2026-07-08

## 当前目标

第一阶段目标是尽快打通可实盘测试的只读闭环：

1. 管理员维护业务用户与交易账户。
2. 管理员或账户所属用户为交易账户配置 Binance API Key / Secret。
3. 系统同步 Binance 合约账户真实余额、持仓和 Hedge Mode。
4. 基于真实持仓生成 `plan_only` 执行计划。
5. 在风控审计下手动查看、确认或导出计划。

第一阶段默认免登录，`auth.login_required=false`，默认操作者为 `admin_001`。

## 产品原则

- 本系统的使用者是管理员：管理员运行整个平台。业务用户只是交易账户的归属方（提供账号/API 凭证），策略由平台提供并由管理员挂载运行，业务用户不设计、不维护、不运行策略。
- 管理员不属于业务用户。
- API Key / Secret 跟随交易账户和所属业务用户，不属于管理员。
- 用户账户页只承载业务用户和交易账户关系，不放策略实例、运行配置等策略维护内容。
- 策略是系统维护的，应放在策略配置、执行计划、币种详情、风控中心等独立页面。
- 页面设计应对齐最初的控制台设计图：清晰的侧边导航、顶部指标、主表/主图、事件时间线和管理员风控中心，而不是堆叠式后台表格。

## 已完成

### 后端

- 支持 MySQL 存储，并通过 `config.local.json` 使用本地 MySQL 配置。
- 支持免登录模式和默认管理员操作者。
- 支持用户会话、管理员/业务用户权限过滤。
- 支持 Binance API Key / Secret 使用 Windows DPAPI 加密保存。
- 支持 Binance 合约账户只读同步：
  - 账户信息
  - 持仓风险
  - Hedge Mode
  - 真实余额与未实现盈亏
- 支持基于真实持仓生成第一阶段执行计划：
  - 利润搬运
  - 仓位恢复
  - 单边趋势确认下的亏损腿减仓
  - `plan_only` 风控拦截
- 支持执行计划人工确认与导出审计：
  - `/api/execution-plans/confirm`
  - `/api/execution-plans/export`
  - 确认和导出均写入管理员审计日志
- 新增管理员维护接口：
  - `/api/users/upsert`
  - `/api/accounts/upsert`

### 前端

- 用户账户页收敛为两个区域：
  - 用户列表
  - 账户列表
- 账户列表内嵌：
  - 所属用户
  - API 配置状态
  - API Key / Secret 保存入口
  - Binance 同步入口
  - 同步错误提示
  - Hedge Mode 状态
- 执行计划页支持：
  - 账户选择
  - 生成执行计划
  - 查看风控检查
  - 人工确认记录
  - 导出当前筛选计划 JSON，并写入导出审计
- 页面设计已开始重新对齐最初设计图：
  - 总览页：顶部指标 + 系统策略表 + 币种状态表
  - 策略事件配置页：三类事件参数卡片
  - 币种详情页：顶部币种指标条 + 仓位概览 + 图表 + 事件时间线
  - 风控中心：风控 KPI + 系统风险告警 + 计划风控检查 + 审计日志 + 快捷操作
  - 已清理账户页之外的旧 Binance 大面板和账户运行配置卡片残留

## 最近验证

- `node --check web\app.js` 通过。
- Python 单元测试：`14 tests OK`。
- 本地服务运行在：`http://127.0.0.1:8765`。
- `/api/state` 冒烟通过：
  - 当前用户：`admin_001`
  - 免登录：`true`
  - 存储：`mysql`

## Git 管理

- 已初始化 Git 仓库，默认分支为 `main`。
- 已建立首个提交：`4dc389e chore: initialize project git repository`。
- 已关联远程仓库：
  - `origin`: `https://github.com/yanceylv518/Orbit.git`
- 已配置 `.gitignore`，排除本地敏感配置和运行产物：
  - `config.local.json`
  - `data/`
  - `runtime/`
  - `tmp/`
  - `reports/`
  - `.agents/`
  - `.codex/`
- 已配置 `.gitattributes`，统一文本文件行尾并标记图片/PDF 为二进制。

## 当前风险与注意事项

- 不要泄露 `config.local.json` 中的真实 MySQL 密码或任何真实 API Secret。
- API Key / Secret 页面不应回显明文。
- 当前仍以 `plan_only` / `read_only` 为主，不应直接下单。
- 后续设计调整应以最初设计图为准，避免再次退化成堆表格页面。
- Binance 网络同步失败时要把错误明确展示到账户行内，不要吞掉。

### 策略逻辑已知缺口（详见技术方案 §21）

- **趋势生命周期缺失（最高优先级）**：`base_price`、`high_since_base`、`low_since_base` 和 `*_count_in_trend` 计数器初始化后从不重置。价格单边走过趋势阈值后 symbol 会永久锁死在减仓状态，`max_times_per_trend` 退化为生命周期总上限。需先在设计上定义「趋势结束/回到 BALANCE」的判定与重锚规则。
- **亏损腿补不回**：趋势中被砍到 base 以下的亏损腿，`position_recovery` 没有任何分支重建，回调后对冲结构失效。
- **风控只检测不阻断**：`MAX_SYMBOL_DRAWDOWN`、`ONLY_REDUCE` 等风控事件不进入事件层 guard，回撤上限形同虚设；且缺少「认输拆对冲全平」的终极止损出口。
- **趋势确认无斜率/时间维度**：慢速阴跌与暴跌被同等对待，叠加陈旧 base 易误判趋势。
- **利润搬运口径待澄清**：`restore_loss_side_only_to_base=true` 且亏损腿已到 base 时，整次搬运（含减盈利腿止盈）被跳过；「用利润恢复亏损腿」是仓位定量口径而非资金划转。
- **成本项待补**：Funding 在失衡对冲中是方向性成本（当前恒为 0）；高频小额搬运有手续费 churn 风险，`min_net_profit` 应覆盖下一次反向平仓成本。

### 平台与文档差异（详见技术方案 §22）

- **凭证加密仅 Windows**：Binance Secret 用 Windows DPAPI 加密，当前 Linux 环境保存会抛 `CredentialError`，相关单测在非 Windows 被跳过。Linux 下需改用 `env:` 引用或另做跨平台凭证后端。
- **运维脚本仅 Windows**：`scripts/` 只有 `.cmd`/`.ps1`，README 为 PowerShell + `C:\Users\...` 路径；Linux 环境未装 `node`，`node --check web/app.js` 无法复现，需补 bash 说明。
- **配置格式为 JSON**：技术方案 §13/§15 写的是 `config.yaml`，实际使用 `config.sample.json` / `config.local.json`。
- **模块为扁平结构**：技术方案 §13 的多层目录未实现，实际为扁平 `src/ddg/`。
- **第一阶段范围**：技术方案 P0 是完整 dry_run 闭环，当前收窄为 `plan_only` 只读优先，以本文件「当前目标」为准。

## 下一步

1. 继续按最初设计图细化视觉样式和信息层级。
2. 补齐账户新增/编辑的更多校验与更友好的错误提示。
3. 强化 Binance 同步后的真实持仓展示：
   - 按账户筛选
   - 按币种筛选
   - 标记 Hedge Mode 不通过的账户
4. 执行计划页补更完整的计划详情抽屉或展开行，展示触发上下文和原始持仓快照。
5. 风控中心继续细化计划风险分类，区分账户同步风险、Hedge Mode 风险、计划动作风险。
6. 每轮开发完成后更新本文件。

### 策略与设计待办（先定设计，再改代码）

> 设计提案已成文：`design/STRATEGY_LOGIC.md`（净敞口 Δ 重述、趋势生命周期状态机、vol 归一化触发、参数一致性约束、仿真验收规范），覆盖以下 7–11 项，待评审后转入实现。
> 实现方案已成文：`design/STRATEGY_IMPLEMENTATION.md`（纯函数内核、表驱动 FSM、四阶段：测试先行 → 离线标定 → plan_only 双跑 → paper/live，含与现有 engine/planning 的迁移映射）。
> 2026-07-08 评审已定（STRATEGY_LOGIC §5.1）：阈值单位 σ 化（弃固定百分比，k₂/k₁ 几何固定）；K 线结构收窄为结构化锚点 + 入场调制器两个回测对比项；趋势生命周期三决策（三条件结束判定 / 现价重锚 / 分批重建）。待办 7、8 的设计部分已定。

7. 定义「趋势生命周期」：趋势结束/回到 BALANCE 的判定，`base_price` 重锚、high/low 与 `*_count_in_trend` 清零规则（技术方案 §21.1）。
8. 定义趋势结束后亏损腿重建规则（§21.2）。
9. 把风控结果接入事件引擎前置 guard，实现 `ONLY_REDUCE` / `PAUSE_SYMBOL` 真正阻断，并补 symbol 级终极止损/拆对冲（§21.3、§21.4）。
10. 趋势确认增加斜率/时间维度（§21.5）。
11. 澄清并按需拆分利润搬运的止盈/加仓逻辑，补 Funding 与手续费 churn 的成本约束（§21.6–§21.8）。

### 工程与文档待办

12. Linux 下补跨平台凭证方案（或统一走 `env:` 引用），并补 bash 启动/校验脚本（技术方案 §22.4、§22.5）。
13. 校准技术方案 §13/§15 的配置格式（JSON）与目录结构描述（扁平），或标注为演进方向（§22.1、§22.2）。
