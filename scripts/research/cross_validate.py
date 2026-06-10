"""
三源印证 CLI 工具
=================
- 输入：单事件标题 + 多个信源 URL
- 输出：verified/not_verified + 各 URL 的 tier + 独立信源数
- 写入 reports/cross_validate_<timestamp>.json

用法：
    python scripts/research/cross_validate.py --title "2026年X月X日..." --source <url1> --source <url2> --source <url3>
    python scripts/research/cross_validate.py --title "..." --source <url1>   # 仅 1 源 → not_verified
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / 'data'
SOURCES_FILE = DATA_DIR / 'sources.yaml'
REPORTS_DIR = SCRIPT_DIR / 'reports'

import yaml


def load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def get_domain(url: str) -> str:
    try:
        return urlparse(url).netloc
    except Exception:
        return ''


def classify_source(url: str, sources: dict) -> dict:
    """对单个 URL 做信源分级。"""
    # 黑名单
    for entry in sources.get('blacklisted', []):
        if entry.get('pattern', '') in url:
            return {
                'url': url,
                'domain': get_domain(url),
                'tier': 'blacklisted',
                'reliability': 'low',
                'action': 'SKIP - 黑名单信源'
            }
    # 官方/数据
    official_domains = {
        'dce.com.cn', 'shfe.com.cn', 'czce.com.cn', 'gfex.com.cn', 'ine.cn',
        'csrc.gov.cn', 'stats.gov.cn', 'moa.gov.cn', 'customs.gov.cn',
        'usda.gov', 'fao.org'
    }
    domain = get_domain(url)
    for od in official_domains:
        if od in domain:
            return {
                'url': url,
                'domain': domain,
                'tier': 'official',
                'reliability': 'high',
                'action': 'ACCEPT - 官方/数据源'
            }
    # 默认中等
    return {
        'url': url,
        'domain': domain,
        'tier': 'unknown',
        'reliability': 'medium',
        'action': 'ACCEPT - 需人工核实（非官方但非黑名单）'
    }


def cross_validate(title: str, urls: list, sources: dict) -> dict:
    """执行三源印证。"""
    classified = [classify_source(u, sources) for u in urls]
    # 过滤掉黑名单
    accepted = [c for c in classified if c['tier'] != 'blacklisted']
    skipped = [c for c in classified if c['tier'] == 'blacklisted']
    # 独立信源（按 domain 去重）
    unique_domains = set(c['domain'] for c in accepted)
    independent_count = len(unique_domains)

    verified = independent_count >= 3

    return {
        'title': title,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'sources_total': len(urls),
        'sources_accepted': len(accepted),
        'sources_skipped': len(skipped),
        'independent_domains': independent_count,
        'verified': verified,
        'verdict': '✅ VERIFIED - 三源印证通过' if verified else f'⚠️ NOT_VERIFIED - 需要 {max(0, 3 - independent_count)} 个独立源',
        'accepted': accepted,
        'skipped': skipped,
    }


def main():
    parser = argparse.ArgumentParser(
        description='三源印证工具 - 验证单事件的多源可信度',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument('--title', required=True, help='事件标题')
    parser.add_argument('--source', action='append', required=True, help='信源 URL（可多次）')
    parser.add_argument('--save', action='store_true', help='保存到 reports/')

    args = parser.parse_args()
    sources = load_yaml(SOURCES_FILE)
    result = cross_validate(args.title, args.source, sources)

    # 控制台输出
    print("=" * 70)
    print(f"事件: {result['title']}")
    print(f"时间: {result['timestamp']}")
    print("=" * 70)
    print(f"信源总数:     {result['sources_total']}")
    print(f"已接受:       {result['sources_accepted']}")
    print(f"已跳过(黑名单): {result['sources_skipped']}")
    print(f"独立信源数:   {result['independent_domains']} (去重后)")
    print(f"\n>>> {result['verdict']}")
    print()

    print("--- 已接受信源 ---")
    for s in result['accepted']:
        print(f"  [{s['tier']:<12}] {s['domain']:<30} {s['action']}")
    if result['skipped']:
        print("\n--- 跳过信源 ---")
        for s in result['skipped']:
            print(f"  [{s['tier']:<12}] {s['domain']:<30} {s['action']}")

    if args.save:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        out = REPORTS_DIR / f'cross_validate_{ts}.json'
        with open(out, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\n💾 已保存: {out}")

    # 退出码：verified=0, not_verified=1
    sys.exit(0 if result['verified'] else 1)


if __name__ == '__main__':
    main()
