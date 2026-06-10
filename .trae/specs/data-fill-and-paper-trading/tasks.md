# Tasks

- [x] Task 1: 搭建 scripts/data 目录与下载器
  - [x] SubTask 1.1: 创建 `scripts/data/__init__.py` + `__main__.py`（提供 `python -m scripts.data` 入口）
  - [x] SubTask 1.2: 实现 `download_futures_continuous.py`：20 个品种清单 + argparse + 限流 + 重试 + Parquet 落地
  - [x] SubTask 1.3: 实现 `verify_cta_research.py`：扫描 parquet，输出 verify_report_*.json

- [x] Task 2: 拉取 20 个品种历史数据
  - [x] SubTask 2.1: 拉 RB / I / CU / AU / AG / NI（黑色 + 有色 + 贵金属，6 个）
  - [x] SubTask 2.2: 拉 Y / P / M / C / SR / CF（农产品，6 个）
  - [x] SubTask 2.3: 拉 TA / MA / FG / SA / RU / BU / FU（化工 + 能源，7 个）
  - [x] SubTask 2.4: 拉 IF（金融期货，1 个）
  - [x] SubTask 2.5: 跑 `verify_cta_research.py` 输出完整性报告（实际：20/20 成功，平均 91.97% 覆盖率）

- [x] Task 3: 用真实数据重跑全量压测
  - [x] SubTask 3.1: 跑 `python tests/stress/run_stress_suite.py --all --sims 10000`（已完成，14.6s）
  - [x] SubTask 3.2: 对比前后两次 `STRESS_SUMMARY_*.md`，重点看 `data_health` / `monte_carlo` 变化（健康度 0→70，walkthrough diff 已修复）
  - [x] SubTask 3.3: 把压测结果作为"上 Paper Trading"前的基线

- [x] Task 4: 搭建 Paper Trading 框架
  - [x] SubTask 4.1: `paper_trading/__init__.py` + `config.py`（初始资金 / 风控阈值 / 交易时段）
  - [x] SubTask 4.2: `sim_broker.py`：订单表 + 成交表 + 持仓表 + 日终结算（T+1 撮合占位 + 已实现 PnL 累加）
  - [x] SubTask 4.3: `risk_gate.py`：4 道闸（组合止损 / Layer2 / 单笔止损 / 单日风险）
  - [x] SubTask 4.4: `kill_switch.py`：扫描 `STOP_PAPER.flag` → 紧急平仓
  - [x] SubTask 4.5: `live_runner.py`：5 分钟轮询 + 调扫描器 + 调风控 + 调模拟券商（支持 --dry-run）

- [x] Task 5: 端到端验证
  - [x] SubTask 5.1: `tests/paper/test_sim_broker.py`：下单→T+1 撮合→加仓均价加权→反手→平仓 PnL→撤单→多日 NAV（6/6 通过）
  - [x] SubTask 5.2: `tests/paper/test_risk_gate.py`：触发 4 道闸（组合止损 / Layer2 / 单笔止损 / 单日风险）+ 正常放行（5/5 通过）
  - [x] SubTask 5.3: `python -m paper_trading.live_runner --dry-run --date 2025-06-05` 干跑一日（拉到 20 品种价 + 1 信号 + 退出 0）

- [x] Task 6: 日终归档与周报
  - [x] SubTask 6.1: `scripts/paper/daily_archive.py`：DB 复制 + NAV snapshot CSV + 周报 Markdown
  - [x] SubTask 6.2: 用 2025-06-03 ~ 2025-06-05 三天数据跑 multi_day_simulator + weekly_report（18 单成交、周收益 +1,760、胜率 33.3%、最大回撤 0.79%）

# Task Dependencies
- Task 2 依赖 Task 1
- Task 3 依赖 Task 2（必须有真实数据）
- Task 4 与 Task 3 可并行
- Task 5 依赖 Task 4
- Task 6 依赖 Task 4
