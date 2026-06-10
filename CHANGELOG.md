# Changelog

本项目的所有重要变更都记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Fixed

- 修复 live_tracker.py 风控标志未被开仓逻辑检查的严重缺陷
- 修复信号融合器 Sharpe 比率计算不一致（np.sqrt(len) 改为 np.sqrt(252)）
- 修复路径一回测引擎前视偏差（改用 T+1 开盘价执行）
- 消除路径一硬编码路径（改为环境变量 + 自动探测）
- 修复 mean_revert_signal 和 volatility_signal 信号强度统一为 0.5 的问题
- 修复 OpenCtpBroker 报单缺 ExchangeID 字段的 148 错误（自动从合约代码推断 6 所交易所）
- 修复 SimNow 新账号下单报 42 结算结果未确认（登录后自动 ReqSettlementInfoConfirm）
- 修复 ExecutionEngine.__init__ 无条件 connect 重复导致二次 ReqAuthenticate 失败（加 is_connected 判断）
- 修复 refactor 引入的 4 个 bug：
  - `position_sizer.py` 残留 `raw` 未定义变量（改 `raw_lots`）
  - `execution_engine.py` 调用 `risk.current_level` / `risk.risk_level()`（应为 `risk.risk_level` property）
  - `PendingSignal` 缺 `entry_price` 字段（`engine._execute` 用到）
  - 兼容 `account_state["current_equity"]` 旧字段名
  - 测试断言期望 `reason == "risk_block"`（去掉后缀 `:level2_no_new`）
- 修复 live_tracker.py 的 2 个 bug：
  - `__init__` 漏初始化 `_risk_no_new_positions` / `_risk_half_position`（daily 阶段 L376 必报 AttributeError）
  - `PARAMS` 缺 `trend_pct_rank_high/low` / `trend_atr_stop_mult` / `trend_atr_take_mult` / `trend_max_hold_days` 5 个字段（`trend_entry_enabled=True` 时 L117-131 必报 AttributeError）

### Added

- 创建路径一 requirements.txt
- 将 path1_ai_enhanced/README.py 重命名为 README.md
- 创建项目级 CHANGELOG.md
- **架构调整：通用 CTP 实盘层抽到 `common/execution/`**（关键）
  - 新建 `common/execution/` 目录，6 个文件迁出 path2/execution/ → 跨 path 共享
  - 新建 `common/execution/base_sizer.py`：`BaseSizer` 抽象类 + `FixedSizer` 缺省 1 手 + `SizerDecision` 共享 dataclass
  - 改 `ExecutionEngine`：自包含、不再依赖 `signal_fusion.py`，新增 `GenericFusedSignal` duck-typing 协议
  - `PositionSizer` 改为继承 `BaseSizer`，向后兼容旧调用
  - 4 个测试脚本 (`simnow_e2e_test.py` / `openctp_smoke.py` / `qry_instrument.py` / `simnow_live_test.py`) 改 import + 加 `sys.path` 注入
  - 5 场景 Mock E2E 回归全过 ✅
- 修 `ctp_broker.py` 损坏缩进：用 `_OPENCTP_TRADER_SPI = object` dummy base class 替代条件性 if-wrapping，让模块在没装 `openctp-ctp` 时也能 import
- 修 `push_notifier.py` / `bridge_publisher.py` 的 `requests` 硬依赖 → 可选依赖（缺了降级 dryrun）
- 修 `confirmation_bridge.py` 的 `fastapi` 硬依赖 → 懒加载（`common.execution` 不再强制要求 fastapi）
- **补 RM（菜粕）真实数据到 cta_research**：2774 行，2015-01-05 ~ 2026-06-08（AKShare `futures_main_sina` 拉取）。原 cta_research 只有 M（豆粕）没有 RM（菜粕），3 品种策略里 RM 实际是空跑
- **写 `path2_lightweight/live_tracker_ctp.py`**：继承 `LiveTracker`，override `_execute_open/_execute_close` 改用 `common.execution.build_broker()` 真下单，支持 `--live` 切真 CTP / dry-run 默认；3 品种交易所映射（TA→CZCE、RM→DCE、MA→CZCE）；CTP 主力合约代码（TA607/RM607/MA607，**7x24 实测**）；所有订单写 `tracking/ctp_order_log.json`；新增 `panic` 一键全平模式
- **SimNow 真实链路全跑通**（2026-06-09 17:04）：7x24 前置 `tcp://182.254.243.31:40001` 登录 OK，结算单 OK；daily --live 5/5 阶段全部跑通：①数据更新 ②信号扫描+真下单 ③风控 GREEN ④日报 ⑤邮件
  - 实测发出 2 笔：TA607 空 1手 @6242, MA607 多 1手 @2963（盘后 15:00 后 CTP 自动撤单，最终持仓 `{}`）
  - 顺带修了 4 个串行 bug：
    - `data_updater.py` AKShare 拉的数据 `date` 列 str/Timestamp 混存导致 sort_values 失败（统一 `pd.to_datetime`）
    - `live_tracker.py` `_save_state` 用 `default=str` 把 numpy.float64 强制转字符串（改 `default=float`）
    - `live_tracker.py` `unrealized_pnl` 计算时 `pos['entry_price']` 可能是 str（加 `float()` 兜底）
    - `live_tracker_ctp.py` `_execute_close` 同上（加 `float()` 兜底）
    - `email_sender.py` 邮件模板 `entry_price` 可能是 str（加 `float()` 兜底）
- **补 `path2_lightweight/verify_3products.py`**：3 品种信号验证脚本（不写 state, 不发邮件, 跑本地 parquet）
- **集成 `MultiNotifier` 到 live_tracker.py + live_tracker_ctp.py**（3 个 push 点）：
  - 父类 `LiveTracker.__init__` 持 `self.notifier = MultiNotifier()`
  - `_execute_open` 末尾 push "开仓" 卡片
  - `_execute_close` 末尾 push "平仓" 卡片
  - `_risk_check_and_execute` 一级/二级/三级风控 push 告警卡片
  - CTP 子类同名方法末尾也加 push (不调 super 时单独触发)
  - 钉钉/Bark webhook 缺时自动 skip + 写日志, 不影响邮件
- **写 `path2_lightweight/run_daily_5d.bat` + `.env.example`**：5 天盯盘期一键批处理
  - `run_daily_5d.bat` 自动从 `.env` 读环境变量, 调 `python live_tracker_ctp.py daily --live`, 日志存 `logs/daily_<日期>_run.log`
  - `.env.example` 列出 CTP/飞书/钉钉/Bark 全部 env 模板
  - 5 天盯盘期用户: ①复制 .env.example 为 .env ②填 CTP 密码 ③每天 17:00 双击 run_daily_5d.bat (或挂到 Windows Task Scheduler)
- **加 LarkWebhookNotifier + LarkCliNotifier** (`common/execution/push_notifier.py`):
  - `LarkWebhookNotifier`: 飞书群机器人 webhook 模式 (跟钉钉一样, 2 分钟配好), 走 interactive 卡片
  - `LarkCliNotifier`: 飞书 lark-cli user 身份 P2P 模式, **0 配置** (实测通过, 自动从 chat-list 拿 open_id)
  - MultiNotifier 现在 4 通道: dingtalk / bark / lark_webhook / lark_cli
- **Trae 平台飞书 0 配实测通过** (2026-06-09 19:04): `lark-cli im +chat-list` 拉 open_id, `+messages-send` 给自己 P2P 发送测试消息 OK
- **部署 2 个 Schedule 任务** (5 天盯盘期):
  - `盯盘期盘后 daily (15:30)` ID `555513c4`, cron `30 15 * * 1-5` (15:30 盘后)
  - `盯盘期夜盘前 daily (21:00)` ID `1fa5cd0b`, cron `0 21 * * 1-5` (21:00 夜盘前, 今晚 21:00 立即跑)
  - 共跑 11 次 (5 个工作日 × 2 个时间点)
- **路径二 CTP 真实下单层**（`path2_lightweight/execution/`）：
  - `ctp_broker.py` — CTP 抽象层（MockCtpBroker / OpenCtpBroker / CtpbeeBroker 三模式 + 工厂）
  - `position_sizer.py` — 10X 激进仓位模型 `floor((Equity-10000)/5000) + 2`
  - `risk_manager.py` — 4 级风控状态机（NORMAL/LEVEL1/LEVEL2/HARDBREAK），40% 硬熔断自动全平
  - `push_notifier.py` — 钉钉 markdown + Bark 推送（缺密钥时自动降级 dryrun）
  - `execution_engine.py` — 信号→风险→仓位→下单→推送 编排器
  - `confirmation_bridge.py` — FastAPI 手机确认桥（HMAC token, `/queue /execute /skip /hardbreak`）
  - `bridge_publisher.py` — 信号推送 HTTP 客户端
  - `simnow_e2e_test.py` — Mock 5 场景端到端回归测试
  - `openctp_smoke.py` — 真实 SimNow 联调脚本（`--dry / --query / --symbol`）
  - `simnow_live_test.py` — 真实 SimNow 全链路测试（信号→推送→broker）
  - `qry_instrument.py` — 合约列表查询辅助脚本
- **Path 2 部署指南**：[path2_lightweight/接手必读.md](path2_lightweight/接手必读.md)
  - 跨机部署踩坑（ctpbee 编译失败、Python 3.14 distutils、SimNow 看穿式前置）
  - 真实联调通过的配置（`simnow_client_test` AppID、AuthCode `0000000000000000`、新前置 `182.254.243.31:30001`）

### Changed

- 路径二 requirements.txt：用 `openctp-ctp>=6.7.11` 替代 `ctpbee`（无需 MSVC 编译）
- `signal_fusion.py` 新增 `execute_signal` 方法 + `execute_fused_signal` 模块级函数，强制在 execute 入口校验 `risk_manager.can_trade()`

## [v0.1.0] - 2026-05-21

### Added

- 路径二：轻量级分位数短线系统（v3版本，双模式，回测+121%）
- 路径一：AI增强多策略系统（四策略信号 + Darwinian权重）
- 定价偏差检测系统（algo1-5算法）
- 信号融合器（路径二主+路径一增强）
- 实盘追踪系统（live_tracker v1.2）
- 三级风控系统（20%/27%/35%回撤阈值）
- QQ邮箱日报/周报推送
- 蒙特卡罗分析和压力测试
- 外部开源参考：ATLAS、FinRobot、OpenAlice、OpenBB
