"""
基本面事件扫描器
================
- 加载 sources.yaml（信源白名单/黑名单）+ news_2026.yaml（事件库）
- 三源印证：≥3 独立源 → verified=true
- 事件强度 1-5 分 + 方向标注
- 提供 CLI：init / list / list-sources / validate / add / verified / stats

用法：
    python scripts/research/fundamental_events.py --init
    python scripts/research/fundamental_events.py --list
    python scripts/research/fundamental_events.py --list-sources
    python scripts/research/fundamental_events.py --validate <url>
    python scripts/research/fundamental_events.py --add --title "..." --symbols "BU,MA" --direction bullish --strength 4 --source <url1> --source <url2>
    python scripts/research/fundamental_events.py --verified
    python scripts/research/fundamental_events.py --stats
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import yaml

# ---------- 路径 ----------
SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / 'data'
SOURCES_FILE = DATA_DIR / 'sources.yaml'
NEWS_FILE = DATA_DIR / 'news_2026.yaml'


def load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def save_yaml(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)


# ---------- 信源校验 ----------
def is_blacklisted(url: str, sources: dict) -> bool:
    for entry in sources.get('blacklisted', []):
        if entry.get('pattern', '') in url:
            return True
    return False


def get_source_tier(url: str, sources: dict) -> str:
    """根据 URL 域名判定信源 tier。"""
    if is_blacklisted(url, sources):
        return 'blacklisted'
    domain_match = {
        'dce.com.cn': 'official',
        'shfe.com.cn': 'official',
        'czce.com.cn': 'official',
        'gfex.com.cn': 'official',
        'ine.cn': 'official',
        'cffex.com.cn': 'official',
        'csrc.gov.cn': 'official',
        'stats.gov.cn': 'official',
        'moa.gov.cn': 'official',
        'customs.gov.cn': 'official',
        'cma.gov.cn': 'official',
        'cfachina.org': 'official',
        'usda.gov': 'official',
        'noaa.gov': 'official',
        'cpc.ncep.noaa.gov': 'official',
        'fao.org': 'official',
    }
    for domain, tier in domain_match.items():
        if domain in url:
            return tier
    # 中等源: 从 sources.yaml paid_sources 动态提取域 (避免再次硬编码)
    medium_domains = set()
    for entry in sources.get('paid_sources', []):
        url_field = entry.get('url', '')
        # 提取 host 部分 (去掉 http://, https://, www., 路径)
        host = url_field.split('//', 1)[-1].split('/', 1)[0].replace('www.', '')
        if host:
            medium_domains.add(host)
    for d in medium_domains:
        if d and d in url:
            return 'medium'
    return 'unknown'  # 默认未知，提示人工核实


def validate_url(url: str, sources: dict) -> dict:
    """校验单个 URL。"""
    tier = get_source_tier(url, sources)
    blacklisted = is_blacklisted(url, sources)
    return {
        'url': url,
        'tier': tier,
        'blacklisted': blacklisted,
        'reliability': 'low' if blacklisted else ('high' if tier == 'official' else 'medium')
    }


# ---------- 三源印证 ----------
def count_independent_sources(event: dict) -> int:
    """独立信源数（按 domain 去重）。"""
    domains = set()
    for src in event.get('sources', []):
        url = src.get('url', '') if isinstance(src, dict) else src
        # 提取 domain
        for part in url.replace('https://', '').replace('http://', '').split('/')[0].split('.'):
            pass
        # 简化：取主域名
        from urllib.parse import urlparse
        try:
            d = urlparse(url).netloc
            if d:
                domains.add(d)
        except Exception:
            pass
    return len(domains)


def auto_verify(event: dict, sources_cfg: dict = None) -> bool:
    """自动判定 verified。

    严格规则（P0 升级）：
      - ≥3 独立域
      - 至少 1 个 official 源
      - tier 权重分 ≥ 4  (official=2 / medium=1 / blacklisted=-1 / unknown=0)
    """
    if sources_cfg is None:
        sources_cfg = load_yaml(SOURCES_FILE)
    domains = set()
    has_official = False
    tier_score = 0
    for src in event.get('sources', []):
        url = src.get('url', '') if isinstance(src, dict) else src
        try:
            d = urlparse(url).netloc
        except Exception:
            d = ''
        if d:
            domains.add(d)
        tier = get_source_tier(url, sources_cfg)
        if tier == 'official':
            has_official = True
            tier_score += 2
        elif tier == 'medium':
            tier_score += 1
        elif tier == 'blacklisted':
            tier_score -= 1
        # unknown = 0
    return len(domains) >= 3 and has_official and tier_score >= 4


# ---------- 事件管理 ----------
def list_events(news: dict, only_verified: bool = False) -> list:
    events = news.get('events', [])
    if only_verified:
        events = [e for e in events if e.get('verified', False)]
    return events


def add_event(news: dict, title: str, symbols: list, direction: str, strength: int,
              source_urls: list, notes: str = '') -> dict:
    sources = []
    for url in source_urls:
        sources.append({'url': url, 'tier': get_source_tier(url, load_yaml(SOURCES_FILE))})
    event = {
        'title': title,
        'date': datetime.now().strftime('%Y-%m-%d'),
        'sources': sources,
        'affected_symbols': symbols,
        'direction': direction,
        'strength': strength,
        'verified': False,  # 写入后由 auto_verify 重算
        'notes': notes,
    }
    event['verified'] = auto_verify(event)
    if 'events' not in news:
        news['events'] = []
    news['events'].append(event)
    return event


def print_event_table(events: list):
    if not events:
        print("（无事件）")
        return
    print(f"{'#':<3} {'date':<11} {'verified':<9} {'strength':<9} {'direction':<10} {'symbols':<20} {'title':<60}")
    print("-" * 130)
    for i, e in enumerate(events, 1):
        verified = '✓ true' if e.get('verified') else '✗ false'
        syms = ','.join(e.get('affected_symbols', []))[:19]
        title = e.get('title', '')[:59]
        print(f"{i:<3} {e.get('date', 'N/A'):<11} {verified:<9} {e.get('strength', '?'):<9} "
              f"{e.get('direction', '?'):<10} {syms:<20} {title:<60}")


def print_stats(news: dict):
    events = news.get('events', [])
    total = len(events)
    verified = sum(1 for e in events if e.get('verified', False))
    by_strength = {}
    by_direction = {}
    for e in events:
        s = e.get('strength', 0)
        by_strength[s] = by_strength.get(s, 0) + 1
        d = e.get('direction', 'unknown')
        by_direction[d] = by_direction.get(d, 0) + 1

    print(f"=== 基本面事件统计 ===")
    print(f"总事件数: {total}")
    print(f"已验证 (verified=true): {verified} ({verified/total*100 if total else 0:.1f}%)")
    print(f"\n按强度分布:")
    for s in sorted(by_strength.keys(), reverse=True):
        print(f"  强度 {s}: {by_strength[s]} 个")
    print(f"\n按方向分布:")
    for d, c in by_direction.items():
        print(f"  {d}: {c} 个")

    # 涉及品种频次
    sym_count = {}
    for e in events:
        for s in e.get('affected_symbols', []):
            sym_count[s] = sym_count.get(s, 0) + 1
    if sym_count:
        print(f"\n涉及品种频次 TOP:")
        for s, c in sorted(sym_count.items(), key=lambda x: -x[1])[:10]:
            print(f"  {s}: {c} 次")


# ---------- 主入口 ----------
def main():
    parser = argparse.ArgumentParser(
        description='基本面事件扫描器（信源校验 + 三源印证 + 强度打分）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument('--init', action='store_true', help='初始化 news_2026.yaml（首次）')
    parser.add_argument('--list', action='store_true', help='列出所有事件')
    parser.add_argument('--list-sources', action='store_true', help='列出信源白名单')
    parser.add_argument('--validate', metavar='URL', help='校验单个 URL 的信源等级')
    parser.add_argument('--add', action='store_true', help='添加事件（需配合 --title/--symbols/--direction/--strength/--source）')
    parser.add_argument('--title', help='事件标题')
    parser.add_argument('--symbols', help='影响品种（逗号分隔）')
    parser.add_argument('--direction', choices=['bullish', 'bearish', 'neutral'], help='方向')
    parser.add_argument('--strength', type=int, choices=[1, 2, 3, 4, 5], help='强度 1-5')
    parser.add_argument('--source', action='append', help='信源 URL（可多次使用）')
    parser.add_argument('--notes', default='', help='备注')
    parser.add_argument('--verified', action='store_true', help='只列出 verified=true 的事件')
    parser.add_argument('--stats', action='store_true', help='显示统计信息')
    parser.add_argument('--json', action='store_true', help='JSON 输出（供 cross_filter 调用）')

    args = parser.parse_args()

    sources = load_yaml(SOURCES_FILE)
    news = load_yaml(NEWS_FILE)

    # 命令分发
    if args.init:
        if not NEWS_FILE.exists():
            # 创建初始模板
            template = {
                'meta': {'updated': datetime.now().strftime('%Y-%m-%d')},
                'events': [],
                'pool': {'core': [], 'observation': [], 'watchlist': []}
            }
            save_yaml(NEWS_FILE, template)
            print(f"✅ 已创建 {NEWS_FILE}")
        else:
            print(f"⚠️ {NEWS_FILE} 已存在，未覆盖")
        return

    if args.list_sources:
        print("=== 🟢 官方/数据类信源（high） ===")
        for s in sources.get('official_sources', []):
            print(f"  {s['name']:<30}  covers: {','.join(s.get('covers', []))[:50]}")
        print(f"\n=== 🟡 行业付费类信源（medium） ===")
        for s in sources.get('paid_sources', []):
            print(f"  {s['name']:<30}  covers: {s.get('covers', 'ALL')}")
        print(f"\n=== 🔴 黑名单 ===")
        for s in sources.get('blacklisted', []):
            print(f"  {s['pattern']:<30}  {s.get('reason', '')}")
        return

    if args.validate:
        result = validate_url(args.validate, sources)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.add:
        if not (args.title and args.symbols and args.direction and args.strength and args.source):
            print("❌ --add 需要 --title / --symbols / --direction / --strength / --source (至少 1 个，可多次)", file=sys.stderr)
            sys.exit(1)
        symbols = [s.strip() for s in args.symbols.split(',')]
        event = add_event(news, args.title, symbols, args.direction, args.strength, args.source, args.notes)
        save_yaml(NEWS_FILE, news)
        print(f"✅ 已添加事件（{len(args.source)} 个源，verified={event['verified']}）")
        print(json.dumps(event, ensure_ascii=False, indent=2))
        return

    if args.verified:
        events = list_events(news, only_verified=True)
        if args.json:
            print(json.dumps(events, ensure_ascii=False, indent=2))
        else:
            print(f"=== ✅ 已验证事件（≥3 独立源）===")
            print_event_table(events)
        return

    if args.stats:
        print_stats(news)
        return

    # 默认 --list
    events = list_events(news)
    if args.json:
        print(json.dumps(events, ensure_ascii=False, indent=2))
    else:
        print(f"=== 全部基本面事件（共 {len(events)} 条）===")
        print_event_table(events)


if __name__ == '__main__':
    main()
