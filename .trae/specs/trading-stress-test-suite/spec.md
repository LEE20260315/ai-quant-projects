# 交易系统压力测试套件 Spec

## Why
MSVC Build Tools 安装期间，恰好是执行全量回归压测的最佳窗口。本次目标是对定价偏差发现系统（`Pricing deviation detection system`）与 `path2_lightweight` 双系统进行全量级压力测试与经典交易压力场景验证，定位交易期间可能出现的风险 bug（信号漂移、止损失效、风控穿透、数据缺失、并发竞态等），并以 `C:\Users\MR.Dong\OneDrive\My Project\cta_research` 为主数据源（CTA Research Parquet 期货/股票连续合约）。本轮压测是用户实盘前的最后一道质量门，关系到 2026 年实盘盈亏曲线。

## What Changes
- 新增统一的压力测试套件入口 `tests/stress/run_stress_suite.py`，串联以下测试：
  - 蒙地卡罗交易模拟（`monte_carlo_trade_simulator.py`）：基于历史成交的 PnL 序列做 10000+ 次随机抽样重排，输出 5% / 50% / 95% 分位、最大回撤分布、破产概率
  - 全量步进交易回测（`full_step_walkthrough.py`）：按交易日逐步重放扫描→信号→下单→持仓→风控→结算全流程，输出每步状态 diff
  - 极端行情压力场景（`extreme_scenarios.py`）：黑天鹅（30%/50% 暴跌）、闪崩、连续亏损、波动率压缩、追加保证金强平、流动性枯竭、夜盘跳空、涨跌停板封板
  - 交易期间风险 bug 探测（`runtime_risk_prober.py`）：针对订单-成交不一致、保证金不足未拦截、止损未触发、风控 Layer2 漏激活、信号日期穿越（T+1 违规）、数据库读写竞态、Parquet 缺失静默、缓存陈旧 8 类高发风险点做断言
- 新增数据探针 `tests/stress/data_health_check.py`，校验 `cta_research` 数据完整性与时间序列连续性
- 新增 `tests/stress/reports/` 目录用于存放每轮压测报告
- 复用 `cta_research` 路径（环境变量 `CTA_RESEARCH_ROOT` 可覆盖），不修改任何业务代码
- 不修改 v1.3 优化计划中已经规划好的清理、路径重构、策略增强等内容

## Impact
- Affected specs: 交易系统测试规范（新增）
- Affected code:
  - 新增：`Pricing deviation detection system/tests/stress/` 整个目录
  - 引用：`Pricing deviation detection system/src/backtest/engine.py`（只读调用 BacktestEngine）
  - 引用：`Pricing deviation detection system/src/risk/monitor.py`（只读调用 RiskMonitor）
  - 引用：`Pricing deviation detection system/src/execution/order_interface.py`（只读调用 OrderInterface）
  - 数据源：`C:\Users\MR.Dong\OneDrive\My Project\cta_research\futures\continuous\*.parquet`
  - 数据源：`C:\Users\MR.Dong\OneDrive\My Project\cta_research\equity\daily\*.parquet`

## ADDED Requirements

### Requirement: 蒙地卡罗交易模拟
系统 SHALL 提供基于历史成交 PnL 序列的蒙地卡罗模拟，验证策略在随机顺序下的稳健性。

#### Scenario: 启动蒙地卡罗模拟
- **WHEN** 用户执行 `python tests/stress/monte_carlo_trade_simulator.py --capital 1000000 --sims 10000 --horizon 252`
- **THEN** 系统从 `cta_research` 加载历史成交，生成 10000 条等长度随机路径
- **AND** 输出分位收益、最大回撤分布、夏普分布、破产概率（资金<30% 初始资金）
- **AND** 将结果写入 `tests/stress/reports/monte_carlo_<timestamp>.json`

#### Scenario: 检测策略脆弱性
- **WHEN** 95 分位收益 < 0 或 破产概率 > 5%
- **THEN** 标记为 `FRAGILE` 并在报告中列出 5 个最差路径的具体日期
- **AND** 输出"策略过度拟合或仓位过重"风险提示

### Requirement: 全量步进交易回测
系统 SHALL 按交易日逐步重放完整交易流程，捕获每一步的状态 diff，定位静默 bug。

#### Scenario: 启动全量步进
- **WHEN** 用户执行 `python tests/stress/full_step_walkthrough.py --start 2024-01-01 --end 2025-12-31`
- **THEN** 系统依次对每个交易日执行：扫描→信号→下单→撮合→持仓→风控检查→结算
- **AND** 每一步保存快照到 `tests/stress/reports/walkthrough_<date>.json`
- **AND** 完成后输出跨日一致性 diff 表（持仓数、可用资金、风险度）

#### Scenario: 发现 T+1 违规
- **WHEN** 检测到 signal_date == entry_date（即信号当日成交，违反 T+1）
- **THEN** 记录为 `BUG-T1-VIOLATION` 并在 `tests/stress/reports/runtime_risk_findings.md` 中列出

### Requirement: 极端行情压力场景
系统 SHALL 模拟 8 类极端场景，验证系统在极端条件下的存活能力。

#### Scenario: 黑天鹅事件
- **WHEN** 模拟单日 30% / 50% 暴跌插入到历史 PnL 序列中
- **THEN** 计算最终资金、最大回撤、是否触发组合止损（12%）、是否触发 Layer2（10%）
- **AND** 标记是否"幸存"（资金 > 30% 初始资金）

#### Scenario: 夜盘跳空 + 涨跌停封板
- **WHEN** 模拟隔夜跳空 5% 且开盘触及涨跌停板无法成交
- **THEN** 检查止损单是否在下一交易日恢复流动性后正确触发
- **AND** 检查风控是否将"无法成交"状态升级为风控事件

### Requirement: 交易期间风险 bug 探测
系统 SHALL 针对 8 类高频风险点做主动断言探测，输出明确的可修复 bug 列表。

#### Scenario: 探测订单-成交不一致
- **WHEN** 模拟下单数量 ≠ 实际成交数量（即部分成交或撤单异常）
- **THEN** 记录 `BUG-ORDER-MISMATCH` 包含订单号、品种、差异数量

#### Scenario: 探测止损未触发
- **WHEN** 持仓浮亏超过止损阈值但未触发平仓
- **THEN** 记录 `BUG-STOP-LOSS-FAIL` 包含品种、亏损金额、应触发价格、实际成交价

#### Scenario: 探测风控穿透
- **WHEN** 组合回撤突破 12% 阈值但未激活组合止损
- **THEN** 记录 `BUG-RISK-BYPASS` 包含当时实际回撤、应激活时间、实际激活时间

#### Scenario: 探测数据缺失静默
- **WHEN** 某个期货品种在 `cta_research` 中缺失某日 Parquet 数据
- **THEN** 扫描器应明确报警而非使用上一日数据近似
- **AND** 记录 `BUG-DATA-MISSING-SILENT` 包含品种、缺失日期、是否被静默处理

### Requirement: 数据健康度校验
系统 SHALL 在每次压测启动前对 `cta_research` 做基础健康度校验，避免在脏数据上做无意义压测。

#### Scenario: 启动数据校验
- **WHEN** 用户执行 `python tests/stress/data_health_check.py`
- **THEN** 检查 `cta_research` 下所有 Parquet 文件存在性、时间序列连续性、缺失日期数、价格异常（涨跌幅 > 20%）
- **AND** 输出 `tests/stress/reports/data_health_<timestamp>.json` 与健康度评分 0~100

#### Scenario: 数据不健康时阻断压测
- **WHEN** 健康度评分 < 60 或存在关键品种（成交量 TOP10）数据缺失
- **THEN** 提示用户修复数据后再启动压测

### Requirement: 压测套件统一入口
系统 SHALL 提供单一入口脚本串联所有压测，避免重复配置。

#### Scenario: 全量压测入口
- **WHEN** 用户执行 `python tests/stress/run_stress_suite.py --all --report-dir tests/stress/reports/`
- **THEN** 按顺序执行：数据健康度 → 全量步进 → 极端场景 → 蒙地卡罗 → 风险 bug 探测
- **AND** 生成总报告 `tests/stress/reports/STRESS_SUMMARY_<timestamp>.md` 包含每项测试的结论与风险等级

#### Scenario: 单项压测
- **WHEN** 用户执行 `python tests/stress/run_stress_suite.py --only monte_carlo`
- **THEN** 仅运行蒙地卡罗测试

## MODIFIED Requirements
无（本次仅新增测试套件，不修改任何业务逻辑）

## REMOVED Requirements
无
