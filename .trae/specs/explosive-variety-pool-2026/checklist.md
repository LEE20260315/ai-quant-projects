# Checklist

## 基本面事件工作流
- [ ] YAML 数据格式定义完整（事件/信源/品种/方向/强度/时间/verified）
- [ ] 至少 8 个可信信源配置（官方 6+ 付费 2+）
- [ ] 低质信源黑名单生效（公众号/自媒体/论坛被跳过）
- [ ] 三源印证机制：≥3 独立源 → verified=true
- [ ] 事件强度 1-5 打分
- [ ] 方向标注 bullish/bearish/neutral
- [ ] 跨周聚合到 `cta_research/news/2026.yaml`
- [ ] 单事件印证 CLI 工具可独立调用
- [ ] `skipped_sources.log` 记录被跳过的低质信源

## 技术面爆品扫描
- [ ] 加载 20 品种 parquet（不报错/不修改数据）
- [ ] 振幅 ≥ 20% 筛选
- [ ] ADX(14) > 25 筛选
- [ ] MA 多/空头排列判定
- [ ] 波动率比 > 1.2
- [ ] 日均成交额 > 50 亿
- [ ] 综合分 = 振幅×0.3 + ADX×0.2 + 趋势×0.3 + 波动×0.2
- [ ] Top N 输出 JSON
- [ ] 阶段判定（启动/主升/末段/退潮）正确
- [ ] `qualified: false` 留作参考，不进 Top

## 双轨综合筛选
- [ ] 基本面 verified=true ∩ 技术面 Top N
- [ ] 加权排序：基本面强度×0.5 + 技术面综合分×0.5
- [ ] Top 5 输出 Markdown
- [ ] 每个候选含入选理由
- [ ] 建议分层（core/observation/watchlist）输出
- [ ] 待人工确认，不自动写入 pool

## 品种池分层
- [ ] core / observation / watchlist 三层
- [ ] `load_pool()` / `update_pool()` / `save_pool()` API
- [ ] 持久化到 `cta_research/pools/2026.json`
- [ ] `update_log` 追加（最近 20 条）
- [ ] `version` 语义化版本递增
- [ ] 单元测试：load/save/版本/log 全部通过

## Paper 5 天验证
- [ ] `--pool-mode dynamic --validate-days 5` 启动成功
- [ ] 每天记录：信号数 / 实际成交 / 持仓峰值 / 保证金 / 风控触发
- [ ] 输出 `validation_report_5d.md`
- [ ] 资金不足自动降级（core → observation）逻辑生效
- [ ] config.py 读动态池生效
- [ ] `SYMBOLS_FALLBACK` 兜底清单存在

## 定期刷新
- [ ] `refresh_pool.py` 可被 cron / Windows Task Scheduler 触发
- [ ] 周日 20:00 定时配置就绪
- [ ] 阶段自动调整分层：启动→core / 末段→observation
- [ ] 退潮期降级保留人工确认（不自动 watchlist）
- [ ] 输出 `pool_refresh_log_<week>.md`（diff 形式）
- [ ] update_log 记录 `auto_demote: true/false`

## 不破坏现有功能
- [ ] 不修改 `Pricing deviation detection system/src/` 业务代码
- [ ] 不修改 `paper_trading/sim_broker.py` / `risk_gate.py` / `kill_switch.py`
- [ ] 不修改 20 品种历史 parquet 数据
- [ ] 原 3 个品种的回测/历史结果不丢失
- [ ] paper_trading 已有测试全部通过（不退步）
