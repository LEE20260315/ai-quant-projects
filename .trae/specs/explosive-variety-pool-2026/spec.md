# 2026 爆品品种池筛选 Spec

## Why
当前 3 个交易品种是基于历史价格表现筛选的，2026 年基本面（天气/产业/宏观）已发生显著变化，原有筛选标准无法识别今年的"爆品"机会。本 Spec 目标是建立**技术面+基本面双轨筛选**的品种池工作流，先用半人工方法定 3~5 个候选，再以 Paper Trading 5 天验证，最终替换现有 3 个品种进入实盘候选。

## What Changes
- 新增 `scripts/research/fundamental_events.py`：基本面事件扫描器（多源信息聚合 + 三源印证 + 标签化）
- 新增 `scripts/research/cross_validate.py`：三源印证 CLI 工具
- 新增 `scripts/research/explosive_scanner.py`：技术面爆品扫描器（振幅/ADX/趋势/波动率比 + 综合打分）
- 新增 `scripts/research/cross_filter.py`：双轨综合筛选（基本面 verified ∩ 技术面 Top N）
- 新增 `scripts/research/refresh_pool.py`：每周日定期刷新 + 阶段判定
- 新增 `cta_research/news/2026.yaml`：基本面事件持久化（按周聚合 + 品种标签 + 方向）
- 新增 `paper_trading/instrument_pool.py`：品种池分层（core/observation/watchlist）
- 新增 `cta_research/pools/2026.json`：品种池持久化
- 修改 `paper_trading/config.py`：把静态品种清单改为读 `instrument_pool.py` 输出
- 复用现有 20 个品种历史数据（`cta_research/futures/continuous/*.parquet`）
- 复用 `paper_trading/live_runner.py`（不改逻辑，仅读新配置）

## Impact
- Affected specs: 新增（2026 爆品品种池筛选）
- Affected code:
  - 新增：`scripts/research/` 整个目录
  - 新增：`cta_research/news/2026.yaml`
  - 新增：`cta_research/pools/2026.json`
  - 新增：`paper_trading/instrument_pool.py`
  - 修改：`paper_trading/config.py`
- **不修改** `Pricing deviation detection system/src/` 业务代码
- **不修改** `paper_trading/sim_broker.py` / `risk_gate.py` / `kill_switch.py`
- **不修改** 20 品种历史 parquet 数据

## ADDED Requirements

### Requirement: 基本面事件数据格式与信源配置
系统 SHALL 定义结构化的事件数据格式（YAML），并维护可信信源白名单 + 低质信源黑名单。

#### Scenario: YAML 数据格式
- WHEN 用户首次执行 `fundamental_events.py --init`
- THEN 在 `cta_research/news/2026.yaml` 创建模板，包含字段：
  - `week`: 2026-W23
  - `events` 列表，每条含：`title` / `date` / `sources`（≥3 URL）/ `affected_symbols` / `direction`（bullish/bearish/neutral）/ `strength`（1-5）/ `verified`（true/false）/ `notes`

#### Scenario: 信源白名单
- WHEN 配置可信信源
- THEN 至少 8 个，分两类：
  - **官方/数据**：5 大交易所公告、农业农村部、国家统计局、海关总署、USDA、FAO
  - **行业付费**：Wind / 同花顺 / 卓创资讯 / Mysteel 钢联 / 天下粮仓
- AND 每个信源标注 `reliability: high` / `medium`

#### Scenario: 低质信源黑名单
- WHEN 检测到信源属于公众号/自媒体/未验证论坛
- THEN 自动跳过，不进 YAML
- AND 记录到 `fundamental_events.py` 的 `skipped_sources` 日志

### Requirement: 基本面事件扫描器
系统 SHALL 扫描可信信源的事件，输出结构化 YAML 供后续筛选使用。

#### Scenario: 启动事件扫描
- WHEN 用户执行 `python scripts/research/fundamental_events.py --week 2026-W23`
- THEN 从白名单信源拉取当周事件
- AND 过滤低质信源
- AND 输出 `cta_research/news/2026-W23.yaml` 与 `cta_research/news/2026.yaml` 追加

#### Scenario: 三源印证
- WHEN 同一事件被扫描到
- THEN 检查独立信源数
- AND ≥ 3 个独立信源 → `verified: true`
- AND 1~2 个信源 → `verified: false`，进观察列表，不进后续筛选

#### Scenario: 事件强度评估
- WHEN 事件通过验证
- THEN 根据"对供需/价格的潜在影响"打 1~5 分：
  - 1-2：噪音/常规更新
  - 3：中等影响（行业政策微调、局部天气异常）
  - 4：较大影响（限产、贸易壁垒、重大天气灾害）
  - 5：结构性黑天鹅（产业革命、宏观剧变）
- AND 标注 `direction: bullish/bearish/neutral`
- AND 标注 `affected_symbols: [RB, I, ...]`

### Requirement: 三源印证工具
系统 SHALL 提供独立 CLI 工具供人工快速验证单条事件。

#### Scenario: 单事件印证
- WHEN 用户执行 `python scripts/research/cross_validate.py --title "2026年X月X日..." --sources <url1> <url2> <url3>`
- THEN 输出印证结果：`verified/not_verified` + 信源数 + 各自立场/数据差异
- AND 输出 `scripts/research/reports/cross_validate_<timestamp>.json`

### Requirement: 技术面爆品扫描器
系统 SHALL 对 20 个品种历史数据计算"爆品分数"，识别趋势性强、波动率放大、流动性充足的品种。

#### Scenario: 启动爆品扫描
- WHEN 用户执行 `python scripts/research/explosive_scanner.py --year 2026 --top 5`
- THEN 加载 `cta_research/futures/continuous/*.parquet` 中 2026-01-01 至今的数据
- AND 对每个品种计算：振幅 / ADX(14) / MA 排列 / 波动率比 / 日均成交额
- AND 输出 `scripts/research/reports/explosive_scan_<date>.json`（按综合分降序）

#### Scenario: 量化筛选规则
- WHEN 计算每个品种分数
- THEN 必须同时满足：
  - 振幅 ≥ 20%（年至今 high-low / 首日 close）
  - ADX(14) > 25
  - MA 呈多头或空头排列
  - 波动率比（当前/1年均值）> 1.2
  - 日均成交额 > 50 亿
- AND 不满足的标 `qualified: false`，留作参考
- AND 综合分 = 振幅×0.3 + ADX归一化×0.2 + 趋势强度×0.3 + 波动率比归一化×0.2

#### Scenario: 趋势阶段判定
- WHEN 候选品种进入 Top N
- THEN 根据 ADX 斜率 + 振幅变化率判定阶段：
  - **启动期**：ADX 从 20→35 区间 + 振幅扩张
  - **主升期**：ADX > 35 且稳定 + MA 发散
  - **末段**：ADX 拐头 + 振幅缩小
  - **退潮期**：反向突破前低/前高
- AND 输出 `trend: long/short` + `phase: <阶段>`

### Requirement: 双轨综合筛选
系统 SHALL 把基本面 verified 事件和技术面 Top N 做交集，输出最终候选池。

#### Scenario: 交集筛选
- WHEN 用户执行 `python scripts/research/cross_filter.py --fundamental 2026-W23 --technical 2026-06-10`
- THEN 加载基本面 `verified=true` 事件涉及的品种 + 技术面 Top 5
- AND 输出**两者交集**的品种
- AND 加权排序：基本面强度×0.5 + 技术面综合分×0.5
- AND 写入 `scripts/research/reports/final_candidates_<date>.md`（人类可读 + Top 5 + 每个候选的入选理由）

#### Scenario: 候选池分层输出
- WHEN 最终候选确认
- THEN `cross_filter.py` 输出建议分层：
  - `core`（核心 3 个）：历史表现 + 今年基本面 + 技术面均确认
  - `observation`（观察 2~5 个）：今年新出现机会，技术面已确认但基本面待持续观察
  - `watchlist`（观望）：仅数据跟踪，不出信号
- AND 输出待人工确认的 Markdown 清单，不自动写入 pool

### Requirement: 品种池分层持久化
系统 SHALL 把人工确认后的分层结果持久化为 JSON，供 Paper Trading 读取。

#### Scenario: 加载/更新/保存池
- WHEN 用户确认候选池分层
- THEN `paper_trading/instrument_pool.py` 提供三个 API：
  - `load_pool() -> dict`：从 `cta_research/pools/2026.json` 读
  - `update_pool(core=[...], observation=[...], watchlist=[...]) -> None`：更新内存对象
  - `save_pool() -> None`：写回 JSON
- AND 每次更新追加 `update_log` 字段（时间 + 触发原因 + 操作人）

#### Scenario: Pool JSON 格式
- WHEN 持久化
- THEN JSON 包含：`core` / `observation` / `watchlist` 三个数组（每项含 symbol / phase / score / added_at）
- AND `update_log` 数组（最近 20 条）
- AND `version` 字段（语义化版本）

### Requirement: Paper Trading 5 天验证
系统 SHALL 在候选池确定后跑 5 天 Paper Trading，验证多品种同开时资金 / 风控承载力。

#### Scenario: 启动 5 天验证
- WHEN 用户执行 `python paper_trading/live_runner.py --pool-mode dynamic --validate-days 5`
- THEN 从 `instrument_pool.load_pool().core` 加载核心品种
- AND 每天记录：信号数 / 实际成交数 / 持仓峰值 / 保证金占用 / 是否触发风控
- AND 5 天后输出 `paper_trading/validation_report_5d.md`：
  - 每日资金快照
  - 能否同时承载 N 个核心品种同开
  - 风控触发次数与原因

#### Scenario: 资金撑不住时降级
- WHEN 5 天内任一日 `core` 池全部触发保证金不足
- THEN `instrument_pool.py` 自动把 `core` 池缩到 2 个，其余降到 `observation`
- AND 输出降级原因到 `validation_report_5d.md`

#### Scenario: 修改 config.py 读动态池
- WHEN 用户确认候选池
- THEN `paper_trading/config.py` 把静态品种清单改为：
  ```python
  from paper_trading.instrument_pool import load_pool
  SYMBOLS = [s["symbol"] for s in load_pool()["core"]]
  ```
- AND 保留 `SYMBOLS_FALLBACK` 静态清单作为兜底（pool 文件缺失时用）

### Requirement: 候选池定期刷新
系统 SHALL 每周日自动重新评估候选池，识别爆品生命周期的阶段变化。

#### Scenario: 周日定时刷新
- WHEN 周日 20:00（可配置）触发 `scripts/research/refresh_pool.py`
- THEN 跑一次 `fundamental_events.py` + `explosive_scanner.py` + `cross_filter.py`
- AND 对比上周候选池：
  - 仍属"启动期/主升期"：保留 core
  - 进入"末段"：从 core 移到 observation
  - "退潮期"：从 observation 移到 watchlist
  - 新进 Top 5：进入 observation 试运行
- AND 自动 `update_pool` + `save_pool`
- AND 输出 `pool_refresh_log_<week>.md`

#### Scenario: 阶段自动降级
- WHEN 某品种从"主升期"进入"末段"
- THEN 自动从 `core` 移到 `observation`
- AND 在 `update_log` 标记 `auto_demote: true` + 原因
- AND 不自动从 `observation` 移到 `watchlist`（保留人工确认）

## MODIFIED Requirements
无（仅新增模块和修改 `config.py` 的品种清单来源，不修改任何业务回测/风控/撮合逻辑）

## REMOVED Requirements
无
