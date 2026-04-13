根据对话历史生成项目总结，包括整体目标（构建适合1万元期货短线交易系统）、关键知识（5个子项目状态、数据源路径、已验证发现、清理结果）、最近行动（全项目扫描验证、文件清理、报告更新、Git初始化、双路径方案确认）和当前计划（双路径并行开发的详细步骤和优先级）。# Project Summary

## Overall Goal
构建一个适合约1万元资金的非高频期货短线/超短线交易系统，通过两条路径并行实验（AI增强型综合系统 vs 轻量级分位数短线系统），使用本地5年数据进行样本外蒙特卡罗回测验证，最终选出最优方案实盘部署。

## Key Knowledge

### 项目结构
- 根目录: `d:\My project\ai-quant-projects-merged`
- 5个独立子项目（各自独立Git管理，已在.gitignore中排除）:
  - `Pricing deviation detection system/` - 核心策略系统（Python）
  - `ATLAS/` - 自我改进AI代理（研究阶段，核心代码缺失）
  - `OpenAlice/` - 文件驱动交易引擎（TypeScript/Beta版）
  - `FinRobot/` - 金融AI智能体平台（Python/AutoGen）
  - `openbb/` - 开源金融数据平台（Python/最成熟）

### 数据源
- 本地路径: `D:\My project\cta_research\`
- 期货连续合约: `futures/continuous/*.parquet`
- 股票日线: `equity/daily/*.parquet`
- 映射数据库: `futures_research.db`
- 覆盖品种: 71个期货品种，21个低保证金品种适合1万元交易

### 核心技术发现
- **Pricing Deviation回测结果**: -11.75%收益，34.48%胜率（需改进）
- **algo5_iron_condor**: 已废弃（年化收益约0%）
- **database.py问题**: 硬编码外部路径，跨机器不可移植
- **缺少requirements.txt**: 依赖管理缺失
- **ATLAS Darwinian权重**: 0.3-2.5范围动态分配策略权重
- **OpenAlice UTA**: 统一交易账户+Trading-as-Git审计
- **OpenBB**: 60+技术指标，50+数据源

### 回测标准参数
- 初始资金: 10,000元
- 手续费: 万1.5，滑点: 万2
- 执行价格: T+1开盘价
- 最大持仓: 1手
- 训练集: 2020-2023（4年样本内）
- 测试集: 2024-2025（2年样本外）

### 评估指标权重
- 年化收益率(25%)、最大回撤(25%)、夏普比率(15%)、胜率(10%)、盈亏比(10%)、Calmar比率(10%)、交易频率(5%)

## Recent Actions

### 已完成（2026-04-13）
1. **[DONE]** 全面扫描5个子项目，确认文件结构和代码状态
2. **[DONE]** 验证Pricing Deviation System核心功能完整性（algo1-5、回测引擎、订单模拟器）
3. **[DONE]** 验证analyze_futures.py脚本正常运行（71个期货品种信息输出）
4. **[DONE]** 确认ATLAS/FinRobot/OpenAlice/OpenBB可运行性
5. **[DONE]** 清理54个冗余文件/目录（35个重复报告+17个__pycache__+1空目录+1临时日志）
6. **[DONE]** 更新项目实盘可行性评估报告（新增更新日志和验证结果）
7. **[DONE]** Git初始化并提交（commit 7981082）
8. **[DONE]** 创建QWEN.md工作目录上下文文件
9. **[DONE]** 制定双路径对比实验方案并获用户批准

### 关键决策
- **双路径并行**: 路径一（AI增强型）和路径二（轻量级）同时开展
- **优先级**: 路径二优先（2-3天出结果），路径一作为研究探索
- **目录结构**: 在项目内新建`path1_ai_enhanced/`和`path2_lightweight/`子目录
- **数据**: 使用本地Parquet数据，2020-2025年，21个低保证金品种
- **方法**: Walk-Forward优化 + 蒙特卡罗模拟（1000次）

## Current Plan

### 路径二：轻量级分位数短线系统（优先）
1. **[TODO]** 创建`path2_lightweight/`目录结构
2. **[TODO]** 实现数据加载器（本地Parquet读取）
3. **[TODO]** 实现核心策略（纯期货单边，分位数入场+ATR止损）
4. **[TODO]** 实现都江堰风控模块
5. **[TODO]** 实现回测引擎（T+1开盘价执行）
6. **[TODO]** 实现Walk-Forward优化器
7. **[TODO]** 运行蒙特卡罗模拟（1000次）
8. **[TODO]** 输出回测结果和分析报告

### 路径一：AI增强型多策略自适应系统（同步）
1. **[TODO]** 创建`path1_ai_enhanced/`目录结构
2. **[TODO]** 实现OpenBB数据接入层
3. **[TODO]** 实现4个并行策略（定价偏差+动量+均值回归+波动率突破）
4. **[TODO]** 实现Darwinian权重动态分配器
5. **[TODO]** 实现PRISM多机制训练器
6. **[TODO]** 实现GuardPipeline安全检查
7. **[TODO]** 实现回测引擎
8. **[TODO]** 运行蒙特卡罗模拟
9. **[TODO]** 输出回测结果和分析报告

### 对比分析
1. **[TODO]** 双路径结果对比（收益/回撤/夏普/胜率/复杂度/实盘可行性）
2. **[TODO]** 更新项目实盘可行性评估报告
3. **[TODO]** 给出最终推荐方案

### 执行顺序
- **第1-2天**: 路径二核心策略 + 基础回测
- **第3天**: 路径二Walk-Forward优化 + 蒙特卡罗模拟
- **第4-5天**: 路径一多策略框架
- **第6-7天**: 路径一Darwinian权重 + 蒙特卡罗模拟
- **第8天**: 双路径对比分析

---

## Summary Metadata
**Update time**: 2026-04-13T04:44:11.068Z 
