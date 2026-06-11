"""
品种池注入器 (P0-2)
====================
读 cross_filter --json 输出 → 写 data/pools/2026.json

供 live_tracker.py 的 load_active_pool() 读取。
无候选时仍写文件 (空 core/observation/watchlist), live_tracker 会回退 SYMBOLS_FALLBACK。

用法:
    python scripts/research/inject_pool.py
    python scripts/research/inject_pool.py --dry-run
    python scripts/research/inject_pool.py --output /path/to/pool.json
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent  # scripts/research → scripts → project_root
DEFAULT_POOL_FILE = PROJECT_ROOT / 'data' / 'pools' / '2026.json'

# 复用 cross_filter 内部函数 (避免 main() 副作用)
sys.path.insert(0, str(SCRIPT_DIR))
from cross_filter import (  # noqa: E402
    load_yaml, get_fundamental_symbols,
    cross_filter as cf_cross_filter, suggest_layering,
    NEWS_FILE,
)
from explosive_scanner import scan_all  # noqa: E402


def build_pool(layering: dict, candidates: list) -> dict:
    """从 cross_filter 输出构造品种池 JSON。"""
    return {
        'updated': datetime.now().isoformat(timespec='seconds'),
        'source': 'scripts/research/cross_filter.py',
        'core': layering.get('core', []),
        'observation': layering.get('observation', []),
        'watchlist': layering.get('watchlist', []),
        'candidates_count': len(candidates),
        'price_in_warning': bool(layering.get('watchlist')) and not layering.get('core'),
    }


def main():
    parser = argparse.ArgumentParser(
        description='将 cross_filter 输出写入品种池 JSON (供 live_tracker 加载)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--year', type=int, default=2026, help='技术面年份')
    parser.add_argument('--top', type=int, default=7, help='Top N 候选')
    parser.add_argument('--output', default=str(DEFAULT_POOL_FILE), help='输出 JSON 路径')
    parser.add_argument('--dry-run', action='store_true', help='只打印不写文件')
    args = parser.parse_args()

    # 1. 加载 + 跑 cross_filter
    news = load_yaml(NEWS_FILE)
    fund_data = get_fundamental_symbols(news)
    print(f"📰 基本面 verified 事件涉及 {len(fund_data)} 个品种")
    tech_results = scan_all(args.year)
    print(f"📈 技术面扫描 {len(tech_results)} 个品种")

    candidates = cf_cross_filter(news, tech_results, top=args.top)
    layering = suggest_layering(candidates)
    print(f"\n✅ 双轨交集命中 {len(candidates)} 个品种")
    print(f"   core={layering['core']}  obs={layering['observation']}  watch={layering['watchlist']}")

    # 2. 构造 + 写文件
    pool = build_pool(layering, candidates)
    if args.dry_run:
        print('\n[DRY-RUN] 不写文件, 输出:')
        print(json.dumps(pool, ensure_ascii=False, indent=2))
        return

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(pool, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\n💾 已写入: {out}")
    print(f"   池大小: core={len(pool['core'])} obs={len(pool['observation'])} "
          f"watch={len(pool['watchlist'])}")
    print(f"   PRICE IN 警告: {pool['price_in_warning']}")


if __name__ == '__main__':
    main()
