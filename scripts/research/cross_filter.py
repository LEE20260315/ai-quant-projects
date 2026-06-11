"""
双轨综合筛选
============
输入：
- data/news_2026.yaml（基本面事件）
- 21 品种 parquet（技术面数据，调用 explosive_scanner.py 的逻辑）

流程：
1. 加载基本面 verified=true 事件涉及的品种
2. 加载技术面扫描结果（调用 explosive_scanner.scan_all）
3. 取交集（基本面 ∩ 技术面 qualified）
4. 加权排序：基本面强度×0.5 + 技术面综合分×0.5
5. 输出 Markdown 报告 + 建议分层

用法：
    python scripts/research/cross_filter.py
    python scripts/research/cross_filter.py --top 7
    python scripts/research/cross_filter.py --output reports/candidates_<date>.md
    python scripts/research/cross_filter.py --json
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import yaml

# 复用 explosive_scanner + fundamental_events
sys.path.insert(0, str(Path(__file__).resolve().parent))
from explosive_scanner import scan_all  # noqa: E402
from fundamental_events import auto_verify, load_yaml as fe_load_yaml, SOURCES_FILE  # noqa: E402

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / 'data'
NEWS_FILE = DATA_DIR / 'news_2026.yaml'
REPORTS_DIR = SCRIPT_DIR / 'reports'

# 权重
WEIGHTS = {
    'fundamental': 0.5,
    'technical': 0.5,
}


def load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def get_fundamental_symbols(news: dict, sources_cfg: dict = None) -> dict:
    """返回通过 auto_verify 校验的事件中各品种涉及的最大强度 + 方向。

    P0 升级：不再信任 yaml 里的 verified 字段，每次都调用 auto_verify 实时算。
    这样 yaml 的 verified 字段失效，逻辑单一来源。
    """
    if sources_cfg is None:
        sources_cfg = fe_load_yaml(SOURCES_FILE)
    sym_data = {}
    for event in news.get('events', []):
        if not auto_verify(event, sources_cfg):
            continue
        strength = event.get('strength', 0)
        direction = event.get('direction', 'neutral')
        for sym in event.get('affected_symbols', []):
            if sym not in sym_data or sym_data[sym]['strength'] < strength:
                sym_data[sym] = {
                    'strength': strength,
                    'direction': direction,
                    'verified': True,
                    'event_title': event.get('title', ''),
                }
    return sym_data


def cross_filter(news: dict, technical_results: list, top: int = 7) -> list:
    """交集筛选 + 加权排序。"""
    fund_data = get_fundamental_symbols(news)

    # 交集
    candidates = []
    for tech in technical_results:
        if 'error' in tech:
            continue
        sym = tech['symbol']
        if sym not in fund_data:
            continue  # 基本面没涉及
        # 计算综合分
        fund_score = fund_data[sym]['strength'] / 5.0  # 归一 [0, 1]
        tech_score = tech.get('score', 0)
        combined = (fund_score * WEIGHTS['fundamental']
                    + tech_score * WEIGHTS['technical'])
        candidates.append({
            'symbol': sym,
            'combined_score': round(combined, 4),
            'fundamental': fund_data[sym],
            'technical': {
                'qualified': tech.get('qualified', False),
                'score': tech.get('score', 0),
                'amplitude_pct': tech.get('amplitude_pct', ''),
                'adx_now': tech.get('adx_now', 0),
                'ma_alignment': tech.get('ma_alignment', ''),
                'phase': tech.get('phase', ''),
                'vol_ratio': tech.get('vol_ratio', 0),
                'chg_30d_pct': tech.get('chg_30d_pct', 0),
            },
        })

    candidates.sort(key=lambda x: x['combined_score'], reverse=True)
    return candidates[:top]


def suggest_layering(candidates: list) -> dict:
    """根据阶段 + 综合分给分层建议。"""
    core, obs, watch = [], [], []
    for c in candidates:
        sym = c['symbol']
        phase = c['technical']['phase']
        adx = c['technical']['adx_now']
        ma = c['technical']['ma_alignment']
        chg_30d = c['technical']['chg_30d_pct']

        # 核心条件：技术 qualified + 主升期/启动期 + ADX > 30
        if c['technical']['qualified'] and phase in ('启动期', '主升期') and adx > 30:
            core.append(sym)
        # 观察：技术 qualified 但阶段不明 / 震荡
        elif c['technical']['qualified'] or phase in ('启动期', '震荡/不明'):
            obs.append(sym)
        # 观望：末段/退潮
        else:
            watch.append(sym)
    return {'core': core, 'observation': obs, 'watchlist': watch}


def render_markdown(candidates: list, layering: dict, top: int) -> str:
    lines = []
    lines.append(f"# 2026 双轨筛选 Top {top} 候选报告")
    lines.append("")
    lines.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**筛选规则**: 基本面 verified=true ∩ 技术面 qualified")
    lines.append(f"**权重**: 基本面×{WEIGHTS['fundamental']} + 技术面×{WEIGHTS['technical']}")
    lines.append("")

    # ⚠️ 反向信号警告
    if not candidates:
        lines.append("## ⚠️ 重要警告：无任何 verified 候选")
        lines.append("")
        lines.append("**所有基本面事件未通过信源门槛（≥3 独立域 + ≥1 official 源 + tier 权重分≥4）**。")
        lines.append("这意味着：")
        lines.append("- 当前所有公开信源都来自自媒体聚合（头条/微信）")
        lines.append("- 缺乏官方源（USDA / NOAA / 交易所 / 统计局）独立印证")
        lines.append("- 建议：等 USDA WASDE 报告 / NOAA CPC 厄尔尼诺公报 / 交易所月报发布后再做决策")
        lines.append("")
    elif layering['core'] == [] and layering['observation'] == [] and layering['watchlist']:
        lines.append("## ⚠️ 重要警告：基本面已 PRICE IN")
        lines.append("")
        lines.append("**所有基本面 verified 涉及的品种，技术面均在末段/退潮期**。")
        lines.append("这意味着：")
        lines.append("- 基本面利好（厄尔尼诺等）已被市场充分定价")
        lines.append("- 当前不是做多时机，反而可能是做空/观望信号")
        lines.append("- 建议：不在这些品种开新仓，等下一轮基本面切换")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 📊 综合候选（按双轨综合分降序）")
    lines.append("")
    lines.append(f"| # | 品种 | 综合分 | 基本面强度 | 基本面方向 | 技术面分 | 振幅 | ADX | MA排列 | 阶段 | 30日涨跌 | 事件 |")
    lines.append("|---|------|--------|------------|------------|----------|------|-----|--------|------|----------|------|")
    for i, c in enumerate(candidates, 1):
        fund = c['fundamental']
        tech = c['technical']
        title = fund['event_title'][:40] + ('...' if len(fund['event_title']) > 40 else '')
        lines.append(
            f"| {i} | **{c['symbol']}** | {c['combined_score']:.3f} | "
            f"{fund['strength']}/5 | {fund['direction']} | "
            f"{tech['score']:.3f} | {tech['amplitude_pct']} | {tech['adx_now']:.1f} | "
            f"{tech['ma_alignment']} | {tech['phase']} | "
            f"{tech['chg_30d_pct']:+.1f}% | {title} |"
        )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 🎯 建议分层")
    lines.append("")
    lines.append("### 核心池 (Core) — 现在可上车")
    if layering['core']:
        for sym in layering['core']:
            lines.append(f"- **{sym}**")
    else:
        lines.append("- （无）")
    lines.append("")
    lines.append("### 观察池 (Observation) — 跟踪为主")
    if layering['observation']:
        for sym in layering['observation']:
            lines.append(f"- {sym}")
    else:
        lines.append("- （无）")
    lines.append("")
    lines.append("### 观望池 (Watchlist) — 不上车")
    if layering['watchlist']:
        for sym in layering['watchlist']:
            lines.append(f"- {sym}")
    else:
        lines.append("- （无）")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## ⚠️ 风控提醒（1 万小资金）")
    lines.append("")
    lines.append("- 单一品种保证金占用 ≤ 30% 总资金（≤ 3000 元）")
    lines.append("- 单一品种最大亏损 ≤ 2% 总资金（≤ 200 元）")
    lines.append("- 严格止损，**爆品不追末段**（末段品种 = 反向信号）")
    lines.append("- 同向持仓不超过 2 个，避免保证金叠加爆仓")
    lines.append("- 1 万小资金建议**核心 2-3 个 + 观察 2-3 个**")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 🔄 下一步")
    lines.append("")
    lines.append("1. 人工确认核心池（可手动调整）")
    lines.append("2. 写入 `data/pools/2026.json`")
    lines.append("3. 跑 Paper Trading 5 天验证（待 paper_trading 集成）")
    lines.append("4. 每周日 20:00 自动刷新（待 refresh_pool.py）")
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description='双轨综合筛选 - 基本面 ∩ 技术面',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument('--top', type=int, default=7, help='Top N 候选（默认 7）')
    parser.add_argument('--year', type=int, default=2026, help='技术面年份')
    parser.add_argument('--output', help='输出 Markdown 文件路径')
    parser.add_argument('--json', action='store_true', help='JSON 输出')
    parser.add_argument('--save', action='store_true', help='默认保存到 reports/')

    args = parser.parse_args()

    # 加载
    news = load_yaml(NEWS_FILE)
    fund_data = get_fundamental_symbols(news)
    print(f"📰 基本面 verified 事件涉及 {len(fund_data)} 个品种: {', '.join(fund_data.keys())}")

    tech_results = scan_all(args.year)
    print(f"📈 技术面扫描 {len(tech_results)} 个品种")

    # 筛选
    candidates = cross_filter(news, tech_results, top=args.top)
    layering = suggest_layering(candidates)

    if args.json:
        print(json.dumps({
            'candidates': candidates,
            'layering': layering,
        }, ensure_ascii=False, indent=2))
    else:
        print(f"\n✅ 双轨交集命中 {len(candidates)} 个品种")
        print(f"   核心: {', '.join(layering['core']) or '（无）'}")
        print(f"   观察: {', '.join(layering['observation']) or '（无）'}")
        print(f"   观望: {', '.join(layering['watchlist']) or '（无）'}")

    # 保存
    if args.output or args.save:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        out = Path(args.output) if args.output else REPORTS_DIR / f'final_candidates_{datetime.now().strftime("%Y%m%d")}.md'
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_markdown(candidates, layering, args.top), encoding='utf-8')
        print(f"\n💾 已保存: {out}")


if __name__ == '__main__':
    main()
