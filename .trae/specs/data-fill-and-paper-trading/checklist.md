# Checklist

## 数据下载
- [ ] `scripts/data/download_futures_continuous.py` 支持 20 个主流期货
- [ ] 限流 0.5s/请求，失败重试 3 次
- [ ] 增量更新（断点续传）
- [ ] Parquet 文件落地到 `cta_research/futures/continuous/`
- [ ] 写出 `download_log_<timestamp>.json`

## 数据自检
- [ ] 扫描全部 Parquet，输出 verify_report_*.json
- [ ] 缺失率 < 5% 视为通过

## 重跑全量压测
- [ ] 用真实数据跑 `run_stress_suite.py --all --sims 10000`
- [ ] 对比前后两次 `STRESS_SUMMARY_*.md`
- [ ] 压测结果作为 Paper Trading 基线

## Paper Trading 模拟券商
- [ ] 订单表 + 成交表 + 持仓表持久化到 SQLite
- [ ] T+1 撮合占位
- [ ] 日终结算（已实现 + 未实现 PnL）

## 风险闸门 4 道
- [ ] 组合止损 12% → 拒单 + 减仓
- [ ] Layer2 10% → 拒新敞口
- [ ] 单笔止损 15% → 自动平仓
- [ ] 单日风险 3% → 当日拒新单

## 紧急停止开关
- [ ] 写 `STOP_PAPER.flag` 后 ≤10s 生效
- [ ] 自动生成所有持仓的市价平仓单
- [ ] 写 `EMERGENCY_STOP_*.log`

## 日内自动运行
- [ ] 5 分钟轮询
- [ ] 调扫描器 → 调风控 → 调模拟券商
- [ ] 日志 INFO 级

## 日终归档
- [ ] `run_paper.sh` 归档日志 + 资金快照
- [ ] 周报 Markdown 可读

## 不破坏现有功能
- [ ] 不修改 `Pricing deviation detection system/src/` 下任何业务代码
- [ ] 不修改 v1.3 优化计划中已规划内容
- [ ] 不接真实 CTP/EMT，纯模拟
