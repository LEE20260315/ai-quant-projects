# scripts/research/ 用法说明

## 目录结构
```
scripts/research/
├── data/                          # 基本面数据（git 跟踪）
│   ├── news_2026.yaml             # 基本面事件库（手工录入）
│   ├── sources.yaml               # 信源白/黑名单
│   └── pools/2026.json            # 品种池分层结果（cross_filter 输出）
├── reports/                       # 扫描报告（gitignore，建议）
│   ├── explosive_scan_<date>.json
│   └── final_candidates_<date>.md
├── fundamental_events.py          # 基本面事件扫描器
├── cross_validate.py              # 三源印证 CLI
├── explosive_scanner.py           # 技术面爆品扫描器
└── cross_filter.py                # 双轨综合筛选
```

## 5 个脚本一句话总结

| 脚本 | 干什么 | 何时用 |
|------|--------|--------|
| `fundamental_events.py` | 事件管理 + 信源校验 + 三源印证 | 录入/审核新事件 |
| `cross_validate.py` | 单事件多源验证 | 拿到新事件想确认 |
| `explosive_scanner.py` | 21 品种量化扫描 + 阶段判定 | 想知道哪些品种在"启动期" |
| `cross_filter.py` | 基本面 ∩ 技术面 交集 + 分层 | **核心：每周出候选池** |
| `refresh_pool.py` | 定期刷新 + 阶段调整 | **待写** |

## 端到端使用流程

### 场景 A：周一早上刷新候选池
```bash
# 1. 跑技术面扫描，看哪些品种在"启动期"
python scripts/research/explosive_scanner.py --top 7

# 2. 跑双轨综合筛选
python scripts/research/cross_filter.py --top 7 --save
# → 生成 reports/final_candidates_<date>.md
```

### 场景 B：拿到新事件，确认是否入基本面库
```bash
# 1. 用三源印证验证
python scripts/research/cross_validate.py \
    --title "2026年X月X日 某地洪水" \
    --source https://news.example.com/1 \
    --source https://news.example.com/2 \
    --source https://news.example.com/3

# 2. 三源印证通过后，录入基本面库
python scripts/research/fundamental_events.py --add \
    --title "2026年X月X日 某地洪水" \
    --symbols "CF,SR" \
    --direction bullish \
    --strength 3 \
    --source https://news.example.com/1 \
    --source https://news.example.com/2 \
    --source https://news.example.com/3 \
    --notes "持续跟踪"
```

### 场景 C：信源治理（删/补信源）
```bash
# 校验单个 URL
python scripts/research/fundamental_events.py --validate https://mp.weixin.qq.com/s/xxx

# 列出所有信源
python scripts/research/fundamental_events.py --list-sources
```

## 关键设计

1. **三源印证**：≥3 独立信源（按 domain 去重）才标 `verified=true`，否则进观察列表
2. **量化筛选**：
   - 振幅 ≥ 20% AND ADX > 25 AND MA 排列 AND 波动比 > 1.2 AND 日均额 > 50 亿
3. **综合分** = 振幅归一×0.3 + ADX归一×0.2 + |趋势强度|×0.3 + 波动比归一×0.2
4. **阶段判定** = ADX 斜率 + 当前值 → 启动期/主升期/末段/退潮期
5. **分层输出**：
   - 核心（Core）：技术 qualified + 启动期/主升期 + ADX>30
   - 观察（Observation）：技术 qualified 或阶段不明
   - 观望（Watchlist）：末段/退潮期

## 1 万小资金风控约束（**永不破**）

- 单一品种保证金 ≤ 30% 总资金
- 单一品种最大亏损 ≤ 2% 总资金
- 同向持仓 ≤ 2 个
- 核心池建议 2-3 个 + 观察池 2-3 个
- 爆品不追末段（末段 = 反向信号）
