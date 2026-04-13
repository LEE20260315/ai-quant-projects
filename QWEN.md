# AI量化交易项目集合 - 工作目录上下文

## 项目概述

这是一个 **AI量化交易研究项目集合**，包含5个独立子项目，目标是探索和构建适合小资金（约1万元）的期货短线交易系统。

**评估时间**: 2026-04-07
**最近更新**: 2026-04-13

---

## 目录结构

```
ai-quant-projects-merged/
├── .gitignore                          # Git忽略规则
├── 项目实盘可行性评估报告.md             # 核心评估报告（已更新2026-04-13验证结果）
├── TECH_FUSION_REPORT.md               # 技术融合方案（ATLAS+OpenAlice+FinRobot+OpenBB→Pricing Deviation）
├── analyze_futures.py                  # 期货品种分析脚本（已验证可运行）
├── QWEN.md                             # 本文件 - 工作目录上下文
│
│ === 5个独立子项目（各自独立Git管理）===
├── Pricing deviation detection system/ # 定价偏差检测系统（核心，Python）
├── ATLAS/                              # 自我改进AI交易代理（研究阶段）
├── OpenAlice/                          # 文件驱动AI交易引擎（Node.js/TypeScript）
├── FinRobot/                           # 金融AI智能体平台（Python/AutoGen）
└── openbb/                             # 开源金融数据平台（Python/ODP）
```

---

## 子项目状态

### 1. Pricing Deviation Detection System（核心项目）
- **技术栈**: Python 3.10+ / SQLite / Parquet / AKShare
- **状态**: 算法完整，回测结果为负（-11.75%），需改进
- **核心组件**:
  - `src/algorithms/` - 5个算法（algo1-5，其中algo5已废弃）
  - `src/backtest/` - 回测引擎（engine.py + engine_updated.py + performance.py）
  - `config/` - YAML配置文件（config.yaml, futures_list.yaml, strategy_params.yaml）
  - `adapters/broker_sim.py` - 订单模拟器
  - `backtest_results/` - 回测结果文件
- **关键问题**:
  - `config/database.py` 硬编码外部路径 `D:\My project\cta_research`
  - 缺少 `requirements.txt`
  - algo5_iron_condor 已废弃（年化收益约0%）

### 2. ATLAS
- **技术栈**: Python / Claude API / Git
- **状态**: 研究阶段，核心代码缺失，仅为架构参考
- **核心创新**: Darwinian权重优化、Autoresearch自改进循环、PRISM多机制训练
- **回测**: 整体-5.91%，部署阶段+22%/173天

### 3. OpenAlice
- **技术栈**: Node.js 22 / TypeScript
- **状态**: Beta版（v0.9.0-beta.8），可运行
- **核心创新**: UTA统一交易账户、Trading-as-Git、GuardPipeline安全检查
- **运行**: `pnpm install && pnpm dev`

### 4. FinRobot
- **技术栈**: Python / AutoGen / BackTrader
- **状态**: 可运行（Python 3.10-3.11）
- **核心功能**: 多Agent协作、金融CoT、自动回测、报告生成
- **运行**: `pip install -r requirements.txt && python run_web_app.py`

### 5. OpenBB
- **技术栈**: Python / FastAPI / ODP
- **状态**: 最成熟的开源项目，34.9k stars
- **核心价值**: 统一数据接入（50+数据源）、60+技术指标
- **运行**: `pip install openbb`

---

## 数据源

项目依赖本地CTA研究数据（不在版本控制中）：
- **路径**: `D:\My project\cta_research\`
- **期货连续合约**: `futures/continuous/*.parquet`
- **股票日线**: `equity/daily/*.parquet`
- **映射数据库**: `futures_research.db`
- **期货-股票映射**: `mappings/futures_stocks_etf.db`

---

## 关键发现（2026-04-13验证）

| 发现 | 详情 |
|------|------|
| 回测结果为负 | 模拟交易收益-11.75%，胜率34.48% |
| algo5已废弃 | 铁鹰策略回测年化收益约0% |
| 硬编码路径 | `database.py` 依赖外部路径，跨机器不可移植 |
| 缺少依赖管理 | 无 `requirements.txt` |
| 文件清理完成 | 删除54个冗余文件/目录 |
| Git已初始化 | 初始提交完成 (commit 7981082) |

---

## 开发约定

### 代码风格
- Python: 遵循PEP 8，UTF-8编码
- 配置文件使用YAML格式
- 数据库使用SQLite + Parquet缓存

### 回测参数
- 初始资金: 10,000元
- 手续费: 万1.5
- 滑点: 万2
- 执行价格: T+1开盘价

### 文档
- 核心文档保留7个，冗余报告已清理
- 评估报告为项目状态的主要记录

---

## 下一步方向（已批准）

**双路径并行实验**：
1. **路径一（AI增强型）**: 综合ATLAS+OpenAlice+FinRobot+OpenBB+Pricing Deviation
2. **路径二（轻量级）**: Pricing Deviation简化为纯期货单边短线交易

**数据**: 本地Parquet，2020-2025年，21个低保证金品种
**方法**: Walk-Forward + 蒙特卡罗模拟（1000次）
