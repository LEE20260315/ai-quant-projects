# Checklist

## 数据源与配置
- [x] 压测套件默认数据源为 `C:\Users\MR.Dong\OneDrive\My Project\cta_research`
- [x] 支持通过环境变量 `CTA_RESEARCH_ROOT` 覆盖
- [x] 启动前自动检测 `cta_research` 是否存在，不存在时立即报错

## 数据健康度校验
- [x] 扫描所有 Parquet 文件，统计每个品种的日期范围与缺失天数
- [x] 标记涨跌幅 > 20% 的异常交易日
- [x] 输出 0~100 健康度评分
- [x] 评分 < 60 或 TOP10 品种缺失时阻断后续压测

## 全量步进交易回放
- [x] 按交易日逐步执行 SCAN → SIGNAL → ORDER → MATCH → POSITION → RISK → SETTLE
- [x] 每步生成快照到 `reports/walkthrough_<date>.json`
- [x] 输出跨日一致性 diff 表（持仓漂移、资金漂移、风险度漂移）
- [x] 支持 `--start` / `--end` 自定义时间窗口

## 极端行情压力场景
- [x] 实现 8 个场景：黑天鹅 30%、黑天鹅 50%、闪崩、连续亏损、波动率压缩、追加保证金强平、夜盘跳空、涨跌停封板
- [x] 每个场景给"幸存/危险"标记
- [x] 标记是否触发组合止损（12%）与 Layer2（10%）

## 蒙地卡罗交易模拟
- [x] 默认 10000 次模拟（可通过 `--sims` 调整）
- [x] 支持 bootstrap / shuffle / block 三种采样模式
- [x] 输出 5% / 50% / 95% 分位、最大回撤分布、夏普分布、破产概率
- [x] 95 分位 < 0 或破产概率 > 5% 时标记 `FRAGILE`

## 交易期间风险 bug 主动探测
- [x] 检测订单-成交不一致 → `BUG-ORDER-MISMATCH`
- [x] 检测保证金不足未拦截 → `BUG-MARGIN-UNCHECKED`
- [x] 检测止损未触发 → `BUG-STOP-LOSS-FAIL`
- [x] 检测风控 Layer2 漏激活 → `BUG-LAYER2-NOT-ACTIVATED`
- [x] 检测 T+1 违规 → `BUG-T1-VIOLATION`
- [x] 检测数据库读写竞态 → `BUG-DB-RACE`
- [x] 检测 Parquet 缺失静默 → `BUG-DATA-MISSING-SILENT`
- [x] 检测缓存陈旧 → `BUG-CACHE-STALE`
- [x] 汇总到 `runtime_risk_findings.md` + `runtime_risk_findings.json`

## 统一入口
- [x] argparse 支持 `--all` / `--only` / `--skip` / `--report-dir` / `--capital` / `--start` / `--end`
- [x] 每一步异常被捕获，不阻断后续测试
- [x] 生成 `STRESS_SUMMARY_<timestamp>.md` 总报告
- [x] 总报告包含每项测试的结论、风险等级、Top 5 风险 bug

## 端到端验证
- [x] 30 个交易日窗口下 `--only data_health` 正常输出
- [x] 30 个交易日窗口下 `--only runtime_risk` 正常输出 `runtime_risk_findings.md`
- [x] `--all` 完整流程能正常生成 `STRESS_SUMMARY_*.md`

## 不破坏现有功能
- [x] 不修改 `Pricing deviation detection system/src/` 下任何业务代码
- [x] 不修改 `path2_lightweight/` 下任何业务代码
- [x] 不修改 `cta_research` 数据
- [x] 不修改 v1.3 优化计划中已规划的清理与路径重构内容
