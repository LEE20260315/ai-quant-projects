"""
技术面爆品扫描器
================
加载 21 个品种 parquet，对 2026 年至今数据计算：
- 振幅（年至今 high-low / 首日 close）
- ADX(14) + 当前/30日前
- MA 排列（5/20/60）
- 波动率比（当前 / 1年均值）
- 日均成交额（volume × close 估算）
- 阶段判定（启动/主升/末段/退潮）
- 综合分 = 振幅×0.3 + ADX归一×0.2 + 趋势强度×0.3 + 波动比归一×0.2

用法：
    python scripts/research/explosive_scanner.py --top 5
    python scripts/research/explosive_scanner.py --top 5 --json
    python scripts/research/explosive_scanner.py --symbol CU
    python scripts/research/explosive_scanner.py --top 5 --no-filter   # 不过滤，只排序
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

# ---------- 路径 ----------
SCRIPT_DIR = Path(__file__).resolve().parent
PARQUET_DIR = Path(r'C:\Users\MR.Dong\OneDrive\My Project\cta_research\futures\continuous')
REPORTS_DIR = SCRIPT_DIR / 'reports'

# ---------- 权重（综合分） ----------
WEIGHTS = {
    'amplitude': 0.3,
    'adx': 0.2,
    'trend': 0.3,
    'volatility': 0.2,
}
# 筛选阈值
THRESHOLDS = {
    'amplitude_min': 0.20,      # 振幅 ≥ 20%
    'adx_min': 20,              # ADX > 20（更宽松，适应启动期）
    'vol_ratio_min': 1.0,       # 波动率比 > 1.0（不再硬卡 1.2）
    'avg_amount_min_yi': 30,    # 日均成交额 > 30 亿（适配 1 万小资金实际能做的品种）
}


# ---------- 工具函数 ----------
def calc_adx(df: pd.DataFrame, period: int = 14):
    """Wilder ADX + DI。返回对齐到 df index 的 Series。"""
    high = df['high']
    low = df['low']
    close = df['close']
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1/period, adjust=False).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1/period, adjust=False).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=1/period, adjust=False).mean()
    return adx, plus_di, minus_di


def ma_alignment(close: pd.Series, short=5, mid=20, long=60) -> dict:
    """MA 排列判定。"""
    s = close.rolling(short).mean().iloc[-1]
    m = close.rolling(mid).mean().iloc[-1]
    l = close.rolling(long).mean().iloc[-1]
    if pd.isna(s) or pd.isna(m) or pd.isna(l):
        return {'label': 'unknown', 'strength': 0}
    if s > m > l:
        return {'label': 'bull_strong', 'strength': 1.0}
    if s < m < l:
        return {'label': 'bear_strong', 'strength': -1.0}
    if s > m:
        return {'label': 'bull_weak', 'strength': 0.5}
    if s < m:
        return {'label': 'bear_weak', 'strength': -0.5}
    return {'label': 'mixed', 'strength': 0}


def phase_judge(adx_series: pd.Series) -> str:
    if len(adx_series) < 60:
        return '数据不足'
    adx_now = adx_series.iloc[-1]
    adx_30 = adx_series.iloc[-30] if len(adx_series) >= 30 else adx_series.iloc[0]
    slope = adx_now - adx_30
    # 启动期：ADX 上升中 + ADX > 20（趋势正在形成，不必等到 30）
    if slope > 5 and adx_now > 20:
        return '启动期'
    # 主升期：ADX > 35 且稳定（斜率小）
    if adx_now > 35 and abs(slope) < 8:
        return '主升期'
    # 末段：ADX 拐头向下 + ADX 较低
    if slope < -3 and adx_now < 25:
        return '末段'
    # 退潮期：ADX 大幅下降
    if slope < -8:
        return '退潮期'
    return '震荡/不明'


def calc_score(metrics: dict) -> float:
    """综合分 = 振幅×0.3 + ADX归一化×0.2 + 趋势强度×0.3 + 波动比归一×0.2"""
    # 振幅归一到 [0, 1]（>50% 视为满分）
    amp_norm = min(metrics['amplitude'] / 0.50, 1.0)
    # ADX 归一到 [0, 1]（60+ 视为满分）
    adx_norm = min(metrics['adx_now'] / 60, 1.0)
    # 趋势强度（已有 -1~1）
    trend_norm = abs(metrics['trend_strength'])
    # 波动比归一到 [0, 1]（>2.0 视为满分）
    vol_norm = min(metrics['vol_ratio'] / 2.0, 1.0)

    score = (amp_norm * WEIGHTS['amplitude']
             + adx_norm * WEIGHTS['adx']
             + trend_norm * WEIGHTS['trend']
             + vol_norm * WEIGHTS['volatility'])
    return round(score, 4)


# ---------- 单品种分析 ----------
def analyze_symbol(parquet_path: Path, year: int = 2026) -> dict:
    df = pd.read_parquet(parquet_path).sort_values('date').reset_index(drop=True)
    df_yr = df[df['date'].str.startswith(str(year))].reset_index(drop=True)

    if len(df_yr) < 30:
        return {'symbol': parquet_path.stem.replace('_main', ''), 'error': f'{year} 数据不足 ({len(df_yr)} 行)'}

    # 用全数据算 ADX（更稳定）
    adx_full, plus_di, minus_di = calc_adx(df, 14)
    if len(adx_full) >= len(df_yr):
        adx_yr = adx_full.iloc[-len(df_yr):].reset_index(drop=True)
    else:
        adx_yr = adx_full

    adx_now = float(adx_yr.iloc[-1])
    adx_30d = float(adx_yr.iloc[-30]) if len(adx_yr) >= 30 else float(adx_yr.iloc[0])
    adx_slope = adx_now - adx_30d

    # 振幅（年内 high-low / 首日 close）
    first_close = float(df_yr['close'].iloc[0])
    amplitude = (float(df_yr['high'].max()) - float(df_yr['low'].min())) / first_close

    # MA 排列
    ma = ma_alignment(df_yr['close'])

    # 波动率（ATR/close，近 20 日）
    atr_20 = (df_yr['high'] - df_yr['low']).rolling(20).mean().iloc[-1]
    cur_vol = atr_20 / df_yr['close'].iloc[-1]
    # 1 年均值（用全数据 ATR/close 的均值）
    if len(df) >= 252:
        full_atr = (df['high'] - df['low']).rolling(20).mean() / df['close']
        avg_vol = full_atr.dropna().mean()
    else:
        avg_vol = cur_vol
    vol_ratio = cur_vol / avg_vol if avg_vol > 0 else 0

    # 日均成交额估算（亿元）= volume × close / 1e8
    df_yr_copy = df_yr.copy()
    df_yr_copy['amount'] = df_yr_copy['volume'] * df_yr_copy['close']
    avg_amount_yi = df_yr_copy['amount'].mean() / 1e8

    # 阶段
    phase = phase_judge(adx_yr)

    # 涨跌幅
    chg_30d = (df_yr['close'].iloc[-1] - df_yr['close'].iloc[-30]) / df_yr['close'].iloc[-30] * 100 if len(df_yr) >= 30 else 0
    chg_60d = (df_yr['close'].iloc[-1] - df_yr['close'].iloc[-60]) / df_yr['close'].iloc[-60] * 100 if len(df_yr) >= 60 else 0

    metrics = {
        'symbol': parquet_path.stem.replace('_main', ''),
        'data_range': f"{df_yr['date'].iloc[0]} ~ {df_yr['date'].iloc[-1]}",
        'rows_2026': len(df_yr),
        'amplitude': round(amplitude, 4),
        'amplitude_pct': f'{amplitude*100:.2f}%',
        'adx_now': round(adx_now, 1),
        'adx_30d_ago': round(adx_30d, 1),
        'adx_slope': round(adx_slope, 1),
        'ma_alignment': ma['label'],
        'trend_strength': ma['strength'],
        'vol_ratio': round(vol_ratio, 2),
        'avg_amount_yi': round(avg_amount_yi, 1),
        'phase': phase,
        'chg_30d_pct': round(chg_30d, 2),
        'chg_60d_pct': round(chg_60d, 2),
        'last_close': float(df_yr['close'].iloc[-1]),
    }

    # 量化筛选规则
    qualified = (
        amplitude >= THRESHOLDS['amplitude_min']
        and adx_now > THRESHOLDS['adx_min']
        and ma['strength'] != 0
        and vol_ratio > THRESHOLDS['vol_ratio_min']
        and avg_amount_yi > THRESHOLDS['avg_amount_min_yi']
    )
    metrics['qualified'] = qualified
    metrics['score'] = calc_score(metrics)
    return metrics


# ---------- 批量扫描 ----------
def scan_all(year: int = 2026) -> list:
    results = []
    for parquet in sorted(PARQUET_DIR.glob('*_main.parquet')):
        try:
            m = analyze_symbol(parquet, year)
            results.append(m)
        except Exception as e:
            results.append({'symbol': parquet.stem.replace('_main', ''), 'error': str(e)})
    # 按综合分排序
    results.sort(key=lambda x: x.get('score', 0), reverse=True)
    return results


def print_table(results: list, top: int = None, show_all: bool = False):
    display = results if show_all or top is None else results[:top]
    print(f"{'#':<3} {'sym':<5} {'振幅':<8} {'ADX':<6} {'adx斜率':<8} {'MA':<12} {'波动比':<7} {'日均额':<8} {'阶段':<10} {'qualified':<10} {'score':<6} {'30d%':<7}")
    print("-" * 130)
    for i, m in enumerate(display, 1):
        if 'error' in m:
            print(f"{i:<3} {m.get('symbol', '?'):<5} ERROR: {m['error']}")
            continue
        qualified_str = '✓' if m['qualified'] else '✗'
        print(f"{i:<3} {m['symbol']:<5} {m['amplitude_pct']:<8} {m['adx_now']:<6.1f} "
              f"{m['adx_slope']:>+7.1f} {m['ma_alignment']:<12} {m['vol_ratio']:<7.2f} "
              f"{m['avg_amount_yi']:>6.1f}亿 {m['phase']:<10} {qualified_str:<10} "
              f"{m['score']:<6.3f} {m['chg_30d_pct']:>+6.1f}%")


def main():
    parser = argparse.ArgumentParser(
        description='技术面爆品扫描器（21 品种 × 5 维量化）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument('--top', type=int, help='只显示前 N 名')
    parser.add_argument('--year', type=int, default=2026, help='目标年份（默认 2026）')
    parser.add_argument('--symbol', help='只分析单个品种')
    parser.add_argument('--no-filter', action='store_true', help='不应用筛选规则（只排序）')
    parser.add_argument('--all', action='store_true', help='显示所有品种（含未通过筛选）')
    parser.add_argument('--json', action='store_true', help='JSON 输出')
    parser.add_argument('--save', action='store_true', help='保存到 reports/')

    args = parser.parse_args()

    if args.symbol:
        parquet = PARQUET_DIR / f'{args.symbol}_main.parquet'
        if not parquet.exists():
            print(f"❌ 找不到 {parquet}", file=sys.stderr)
            sys.exit(1)
        m = analyze_symbol(parquet, args.year)
        print(json.dumps(m, ensure_ascii=False, indent=2) if args.json else None)
        if not args.json:
            for k, v in m.items():
                print(f"  {k:<18}: {v}")
        return

    results = scan_all(args.year)

    if args.no_filter:
        for r in results:
            r['qualified'] = True

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        qualified_count = sum(1 for r in results if r.get('qualified'))
        print(f"=== 2026 爆品扫描（{len(results)} 品种，{qualified_count} 通过筛选）===")
        print(f"筛选规则: 振幅≥{THRESHOLDS['amplitude_min']*100:.0f}% AND ADX>{THRESHOLDS['adx_min']} "
              f"AND MA排列 AND 波动比>{THRESHOLDS['vol_ratio_min']} AND 日均额>{THRESHOLDS['avg_amount_min_yi']}亿")
        print(f"综合分权重: 振幅{WEIGHTS['amplitude']} + ADX{WEIGHTS['adx']} + 趋势{WEIGHTS['trend']} + 波动{WEIGHTS['volatility']}")
        print()
        print_table(results, top=args.top, show_all=args.all)

    if args.save:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        out = REPORTS_DIR / f'explosive_scan_{ts}.json'
        with open(out, 'w', encoding='utf-8') as f:
            json.dump({'timestamp': ts, 'year': args.year, 'thresholds': THRESHOLDS,
                       'weights': WEIGHTS, 'results': results}, f, ensure_ascii=False, indent=2)
        print(f"\n💾 已保存: {out}")


if __name__ == '__main__':
    main()
