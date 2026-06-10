# 数据补齐 + Paper Trading 上线 Spec

## Why
MSVC + Python 环境已就绪，AKShare 可用且能拉通新浪源。前序的"压力测试套件"已交付，但 cta_research 仍为空（健康度=0），整套系统无法在真实数据上验证风险点。本轮目标：把 20 个主流期货连续合约 1~3 年的历史数据补齐 → 用真实数据重跑全部压测 → 搭建 Paper Trading 框架，2~4 周后视结果再切实盘。这是 2026 年实盘前的最后一道门。

## What Changes
- 新增 `scripts/data/download_futures_continuous.py`：批量下载 20 个主流期货主力连续合约，写入 `cta_research/futures/continuous/<SYMBOL>_main.parquet`
- 新增 `scripts/data/verify_cta_research.py`：下载完后的数据完整性自检
- 复用现有 `tests/stress/` 套件：数据补齐后重跑 `--all`，将 `STRESS_SUMMARY_*.md` 与上一次空数据结果对比
- 新增 `paper_trading/` 目录：包含 4 个模块
  - `sim_broker.py`：模拟券商（接收订单 → 撮合 → 持仓 → PnL 结算），不接真实 CTP/EMT
  - `live_runner.py`：日内定时拉 AKShare 最新价 → 跑扫描 → 出信号 → 模拟下单 → 写日志
  - `risk_gate.py`：组合止损 12% / Layer2 10% / 单笔 15% / 单日 3% 四道闸，超阈值立即停单
  - `kill_switch.py`：人工一键停 Paper 交易 + 紧急平仓（写 `STOP_PAPER.flag` 文件触发）
- 新增 `scripts/paper/run_paper.sh`：日终日志归档 + 资金快照 + 周报生成
- 复用现有 20 个期货清单（用户已选定）；开始日期默认 2024-01-01

## Impact
- Affected specs: 新增（数据补齐 + Paper Trading）
- Affected code:
  - 新增：`scripts/data/download_futures_continuous.py`、`scripts/data/verify_cta_research.py`
  - 新增：`paper_trading/sim_broker.py`、`live_runner.py`、`risk_gate.py`、`kill_switch.py`
  - 新增：`scripts/paper/run_paper.sh`
  - 数据源：`C:\Users\MR.Dong\OneDrive\My Project\cta_research\futures\continuous\*.parquet`（写入）
  - 缓存：`Pricing deviation detection system\data\db\system.db`（AKShare 缓存）

## ADDED Requirements

### Requirement: 批量下载 20 个主流期货连续合约
系统 SHALL 通过 AKShare `futures_main_sina` 接口批量下载主力连续合约，落地为 Parquet。

#### Scenario: 启动批量下载
- **WHEN** 用户执行 `python scripts/data/download_futures_continuous.py --start 2024-01-01`
- **THEN** 依次拉取 20 个品种（RB/I/CU/AU/AG/NI/Y/P/M/C/SR/CF/TA/MA/FG/SA/RU/BU/FU/IF）的主力连续合约
- **AND** 每品种限流 0.5s/请求，失败重试 3 次
- **AND** 写入 `cta_research/futures/continuous/<SYMBOL>_main.parquet`，列名统一为 `date/open/high/low/close/volume`
- **AND** 控制台实时输出进度，写 `scripts/data/download_log_<timestamp>.json`

#### Scenario: 单品种失败不阻断
- **WHEN** 某个品种下载失败（如新浪限流、网络中断）
- **THEN** 记录到 `download_log_*.json` 的 `failed` 列表，继续下一个品种
- **AND** 下载结束后汇总成功率

#### Scenario: 增量更新
- **WHEN** 重新执行下载脚本且目标文件已存在
- **THEN** 检查 Parquet 末日期，仅补齐缺失日期（断点续传）

### Requirement: 下载后数据完整性自检
系统 SHALL 在下载完成后自动校验数据时间序列连续性、缺失率、异常涨跌幅。

#### Scenario: 启动自检
- **WHEN** 用户执行 `python scripts/data/verify_cta_research.py`
- **THEN** 扫描 `cta_research/futures/continuous/*.parquet`
- **AND** 给出每个品种：行数 / 日期范围 / 缺失工作日 / 异常涨跌幅（>20%）
- **AND** 输出 `scripts/data/verify_report_<timestamp>.json` + 控制台摘要

#### Scenario: 触发再压测
- **WHEN** 自检通过（缺失率 < 5%）
- **THEN** 提示用户执行 `python tests/stress/run_stress_suite.py --all` 重跑全部压测

### Requirement: Paper Trading 模拟券商
系统 SHALL 提供不接真实 CTP/EMT 的模拟券商，支持完整下单→撮合→持仓→结算流程。

#### Scenario: 模拟下单
- **WHEN** `sim_broker.submit_order(symbol, direction, qty, price, t_date)` 被调用
- **THEN** 校验保证金、撮合（T+1 撮合占位）、更新持仓、返回订单 ID 与成交回报
- **AND** 所有订单与成交写入 `paper_trading/orders.db`（SQLite）

#### Scenario: 日终结算
- **WHEN** 每日 15:30（可配置）调用 `sim_broker.settle(t_date)`
- **THEN** 计算当日已实现 + 未实现 PnL
- **AND** 检查组合止损 / Layer2 / 单笔止损
- **AND** 写 `paper_trading/daily_nav_<date>.json`

### Requirement: 风险闸门（4 道）
系统 SHALL 在订单提交前 + 持仓计算后 4 道闸门检查。

#### Scenario: 组合止损 12%
- **WHEN** 组合回撤达到 12%
- **THEN** 拒绝所有新订单 + 触发减仓（先平亏损最大的持仓）

#### Scenario: Layer2 10%
- **WHEN** 组合回撤达到 10%（但 < 12%）
- **THEN** 拒绝新增敞口 + 标记 `layer2_active=True`

#### Scenario: 单笔止损 15%
- **WHEN** 某持仓浮亏达到开仓价值的 15%
- **THEN** 自动生成平仓单（市价）

#### Scenario: 单日风险 3%
- **WHEN** 当日已实现亏损 ≥ 3% 初始资金
- **THEN** 拒绝当日新订单（仅允许平仓）

### Requirement: 紧急停止开关
系统 SHALL 支持人工一键停止 Paper 交易 + 紧急平仓。

#### Scenario: 写停止标志
- **WHEN** 用户创建 `paper_trading/STOP_PAPER.flag` 文件
- **THEN** `live_runner` 在下一次轮询（≤10s）时检测到并停止接收新信号
- **AND** 自动生成所有持仓的市价平仓单
- **AND** 写 `paper_trading/EMERGENCY_STOP_<timestamp>.log`

### Requirement: 日内自动运行
系统 SHALL 提供日内自动运行器，按 5 分钟轮询拉数据 → 跑扫描 → 出信号 → 模拟下单。

#### Scenario: 启动日内运行
- **WHEN** 用户执行 `python paper_trading/live_runner.py --start 2025-XX-XX`
- **THEN** 在交易时段（9:00-11:30 + 13:00-15:00）每 5 分钟轮询
- **AND** 调 `Pricing deviation detection system/src/scanner/price_deviation_scanner.py` 拿信号
- **AND** 调 `risk_gate.check_*` 通过后调 `sim_broker.submit_order`
- **AND** 所有决策写 `paper_trading/runner_<date>.log`（INFO 级）

### Requirement: 日终归档与周报
系统 SHALL 每日盘后自动归档 + 每周生成可读周报。

#### Scenario: 日终归档
- **WHEN** 用户执行 `bash scripts/paper/run_paper.sh`
- **THEN** 归档当日 `runner_*.log` + 资金快照到 `paper_trading/archive/<YYYY-MM-DD>/`
- **AND** 写 `paper_trading/weekly_report_<week>.md`（人类可读）

## MODIFIED Requirements
无（本次仅新增脚本与 Paper Trading 框架，不修改任何业务代码）

## REMOVED Requirements
无
