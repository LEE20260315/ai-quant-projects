# Tasks

- [x] Task 1: 创建压测套件目录与统一配置
  - [x] SubTask 1.1: 在 `Pricing deviation detection system/tests/stress/` 下创建 `__init__.py`、`config.py`、`cta_research_loader.py`
  - [x] SubTask 1.2: 在 `config.py` 中通过 `CTA_RESEARCH_ROOT` 环境变量指向 `C:\Users\MR.Dong\OneDrive\My Project\cta_research`，并提供 `get_futures_dir()` / `get_equity_dir()` / `get_main_db_path()` 三个 helper
  - [x] SubTask 1.3: 创建 `reports/` 子目录与 `.gitkeep`

- [x] Task 2: 实现数据健康度校验（`data_health_check.py`）
  - [x] SubTask 2.1: 扫描 `cta_research/futures/continuous/*.parquet` 与 `cta_research/equity/daily/*.parquet`，统计每个品种的日期范围、缺失日期、涨跌幅异常（>20%）
  - [x] SubTask 2.2: 评分公式：基础 100 分，按缺失日期数、TOP10 品种缺失、异常涨跌幅三个维度扣分
  - [x] SubTask 2.3: 输出 `data_health_<timestamp>.json` + 控制台人类可读摘要

- [x] Task 3: 实现全量步进交易回放（`full_step_walkthrough.py`）
  - [x] SubTask 3.1: 编写 `WalkthroughStep` 枚举：SCAN → SIGNAL → ORDER → MATCH → POSITION → RISK → SETTLE
  - [x] SubTask 3.2: 对每个交易日调用 `BacktestEngine` 内部组件，串接成完整流程
  - [x] SubTask 3.3: 每步生成快照到 `reports/walkthrough_<date>.json`
  - [x] SubTask 3.4: 完成后输出跨日一致性 diff 表，列出持仓漂移、资金漂移、风险度漂移三种异常

- [x] Task 4: 实现极端行情压力场景（`extreme_scenarios.py`）
  - [x] SubTask 4.1: 实现 8 个场景：黑天鹅 30%、黑天鹅 50%、闪崩 15%→10%、连续亏损 5 笔、波动率压缩、追加保证金 50% 强平、夜盘跳空 5%、涨跌停封板
  - [x] SubTask 4.2: 复用 `EnhancedStressTester` 的核心思想，但接入 `BacktestEngine` 的真实回测输出
  - [x] SubTask 4.3: 输出 `extreme_scenarios_<timestamp>.json`，每个场景给"幸存/危险"标记

- [x] Task 5: 实现蒙地卡罗交易模拟（`monte_carlo_trade_simulator.py`）
  - [x] SubTask 5.1: 从全量步进回放中提取 PnL 序列
  - [x] SubTask 5.2: 使用 numpy 实现置换重采样（不打乱顺序保持时序特征；提供 `--mode bootstrap|shuffle|block` 三种采样模式）
  - [x] SubTask 5.3: 默认 10000 次模拟，输出 5% / 50% / 95% 分位、最大回撤分布、夏普分布、破产概率
  - [x] SubTask 5.4: 输出 `monte_carlo_<timestamp>.json` + 5 条最差路径明细

- [x] Task 6: 实现交易期间风险 bug 主动探测（`runtime_risk_prober.py`）
  - [x] SubTask 6.1: 实现 8 类断言：订单-成交不一致、保证金不足未拦截、止损未触发、风控 Layer2 漏激活、T+1 违规、数据库读写竞态、Parquet 缺失静默、缓存陈旧
  - [x] SubTask 6.2: 每个断言生成 `BUG-<CATEGORY>-<id>` 标签
  - [x] SubTask 6.3: 汇总到 `reports/runtime_risk_findings.md`（人类可读）+ `reports/runtime_risk_findings.json`（机器可读）

- [x] Task 7: 实现统一入口（`run_stress_suite.py`）
  - [x] SubTask 7.1: argparse 支持 `--all` / `--only <name>` / `--skip <name>` / `--report-dir` / `--capital` / `--start` / `--end`
  - [x] SubTask 7.2: 串联 Task 2→3→4→5→6，每一步捕获异常继续下一项
  - [x] SubTask 7.3: 生成 `STRESS_SUMMARY_<timestamp>.md` 总报告，包含每项测试的结论、风险等级、Top 5 风险 bug

- [x] Task 8: 端到端验证
  - [x] SubTask 8.1: 在小窗口（最近 30 个交易日）下跑一次 `--only data_health` 确认能正常输出
  - [x] SubTask 8.2: 跑一次 `--only runtime_risk` 确认能输出 `runtime_risk_findings.md`
  - [x] SubTask 8.3: 跑一次 `--all` 完整流程，确认 `STRESS_SUMMARY_*.md` 正常生成

# Task Dependencies
- Task 2 独立可并行
- Task 3 → Task 4 → Task 5（5 依赖 3 的 PnL 序列；4 可与 3 并行）
- Task 6 依赖 Task 3 的 walkthrough 快照
- Task 7 依赖 Task 2、3、4、5、6 全部完成
- Task 8 依赖 Task 7
