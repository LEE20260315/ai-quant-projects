# Tasks

- [ ] Task 1: 设计基本面事件数据格式与信源配置
  - [ ] SubTask 1.1: 定义 `cta_research/news/2026.yaml` 字段规范（事件/信源/品种/方向/强度/时间/verified）
  - [ ] SubTask 1.2: 配置 8~10 个可信信源（5 大交易所、农业农村部、国家统计局、USDA、FAO、卓创、Mysteel 钢联、天下粮仓）
  - [ ] SubTask 1.3: 定义低质信源黑名单（公众号/自媒体/未验证论坛）

- [ ] Task 2: 实现基本面事件扫描器（`scripts/research/fundamental_events.py`）
  - [ ] SubTask 2.1: 实现 `--init` 创建 YAML 模板
  - [ ] SubTask 2.2: 实现 `--week 2026-W23` 拉取 + 过滤 + 输出
  - [ ] SubTask 2.3: 三源印证机制（≥3 独立源 → verified=true）
  - [ ] SubTask 2.4: 事件强度 1-5 打分 + 方向标注
  - [ ] SubTask 2.5: 输出 `cta_research/news/2026.yaml` + 控制台摘要 + `skipped_sources.log`

- [ ] Task 3: 实现三源印证 CLI 工具（`scripts/research/cross_validate.py`）
  - [ ] SubTask 3.1: CLI：`cross_validate --title "..." --sources <url1> <url2> <url3>`
  - [ ] SubTask 3.2: 输出 `scripts/research/reports/cross_validate_<timestamp>.json`

- [ ] Task 4: 实现技术面爆品扫描器（`scripts/research/explosive_scanner.py`）
  - [ ] SubTask 4.1: 加载 20 个品种 parquet，提取 2026-01-01 至今数据
  - [ ] SubTask 4.2: 计算振幅 / ADX(14) / MA 排列 / 波动率比 / 日均成交额
  - [ ] SubTask 4.3: 量化筛选规则（≥20% / >25 / 排列 / >1.2 / >50亿）
  - [ ] SubTask 4.4: 综合分 = 振幅×0.3 + ADX归一化×0.2 + 趋势强度×0.3 + 波动率比归一化×0.2
  - [ ] SubTask 4.5: 输出 `scripts/research/reports/explosive_scan_<date>.json`
  - [ ] SubTask 4.6: 阶段判定（启动/主升/末段/退潮）输出

- [ ] Task 5: 实现双轨综合筛选（`scripts/research/cross_filter.py`）
  - [ ] SubTask 5.1: 加载基本面 verified=true + 技术面 Top N
  - [ ] SubTask 5.2: 交集筛选 + 加权排序（基本面强度×0.5 + 技术面综合分×0.5）
  - [ ] SubTask 5.3: 输出 `scripts/research/reports/final_candidates_<date>.md`（人类可读 + Top 5 + 入选理由 + 建议分层）

- [ ] Task 6: 实现品种池分层（`paper_trading/instrument_pool.py`）
  - [ ] SubTask 6.1: 定义 Pool 枚举（core/observation/watchlist）
  - [ ] SubTask 6.2: 实现 `load_pool()` / `update_pool()` / `save_pool()` 三个 API
  - [ ] SubTask 6.3: 持久化到 `cta_research/pools/2026.json`（含 update_log + version）
  - [ ] SubTask 6.4: 单元测试（load/save/版本递增/log 追加）

- [ ] Task 7: 修改 Paper Trading 读取品种池
  - [ ] SubTask 7.1: 修改 `paper_trading/config.py`：把 `SYMBOLS` 改为读 `instrument_pool.load_pool()["core"]`
  - [ ] SubTask 7.2: 保留 `SYMBOLS_FALLBACK` 静态兜底清单
  - [ ] SubTask 7.3: 验证 `live_runner.py` 能从动态池读取（dry-run 跑一次）

- [ ] Task 8: 5 天 Paper 验证
  - [ ] SubTask 8.1: 启动 `python paper_trading/live_runner.py --pool-mode dynamic --validate-days 5`
  - [ ] SubTask 8.2: 每天记录：信号数 / 实际成交数 / 持仓峰值 / 保证金占用 / 风控触发
  - [ ] SubTask 8.3: 输出 `paper_trading/validation_report_5d.md`
  - [ ] SubTask 8.4: 资金不足自动降级（core → observation）

- [ ] Task 9: 候选池定期刷新机制（`scripts/research/refresh_pool.py`）
  - [ ] SubTask 9.1: 周日 20:00 定时触发（可配 cron / Windows Task Scheduler）
  - [ ] SubTask 9.2: 阶段自动调整分层（启动→core / 末段→observation / 退潮期→watchlist）
  - [ ] SubTask 9.3: 输出 `pool_refresh_log_<week>.md`（diff 形式：本周 vs 上周）
  - [ ] SubTask 9.4: 退潮期降级需人工确认（不自动从 observation 移到 watchlist）

# Task Dependencies
- Task 1 独立可最先做
- Task 2 + Task 4 互不依赖，可并行
- Task 3 独立可并行
- Task 5 依赖 Task 2 + Task 4
- Task 6 独立可并行
- Task 7 依赖 Task 6
- Task 8 依赖 Task 5 + Task 6 + Task 7
- Task 9 依赖 Task 2 + Task 4 + Task 5 + Task 6
