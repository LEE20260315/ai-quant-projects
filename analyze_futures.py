import pandas as pd
import numpy as np
import os

data_path = "D:/My project/cta_research"

df = pd.read_parquet(f'{data_path}/futures/basic/futures_list.parquet')
print('=' * 80)
print('=== 期货品种基本信息 ===')
print('=' * 80)
print(df[['symbol', 'exchange', 'name', 'contract_multiplier', 'tick_size', 'margin_ratio']].to_string())

volatility_data = []

try:
    rb = pd.read_parquet(f'{data_path}/futures/intraday/RB_2h.parquet')
    if len(rb) > 0:
        rb['atr'] = (rb['high'] - rb['low']).rolling(20).mean()
        rb['atr_pct'] = rb['atr'] / rb['close'] * 100
        avg_atr_pct = rb['atr_pct'].dropna().mean()
        volatility_data.append(('RB', '螺纹钢', avg_atr_pct, 10, 3000, 0.10))
except Exception as e:
    print(f"读取RB数据失败: {e}")

try:
    ag = pd.read_parquet(f'{data_path}/futures/intraday/AG_2h.parquet')
    if len(ag) > 0:
        ag['atr'] = (ag['high'] - ag['low']).rolling(20).mean()
        ag['atr_pct'] = ag['atr'] / ag['close'] * 100
        avg_atr_pct = ag['atr_pct'].dropna().mean()
        volatility_data.append(('AG', '白银', avg_atr_pct, 15, 5000, 0.10))
except Exception as e:
    print(f"读取AG数据失败: {e}")

try:
    au = pd.read_parquet(f'{data_path}/futures/intraday/AU_2h.parquet')
    if len(au) > 0:
        au['atr'] = (au['high'] - au['low']).rolling(20).mean()
        au['atr_pct'] = au['atr'] / au['close'] * 100
        avg_atr_pct = au['atr_pct'].dropna().mean()
        volatility_data.append(('AU', '黄金', avg_atr_pct, 10, 10000, 0.08))
except Exception as e:
    print(f"读取AU数据失败: {e}")

try:
    m = pd.read_parquet(f'{data_path}/futures/intraday/M_2h.parquet')
    if len(m) > 0:
        m['atr'] = (m['high'] - m['low']).rolling(20).mean()
        m['atr_pct'] = m['atr'] / m['close'] * 100
        avg_atr_pct = m['atr_pct'].dropna().mean()
        volatility_data.append(('M', '豆粕', avg_atr_pct, 10, 2000, 0.10))
except Exception as e:
    print(f"读取M数据失败: {e}")

try:
    ma = pd.read_parquet(f'{data_path}/futures/intraday/MA_2h.parquet')
    if len(ma) > 0:
        ma['atr'] = (ma['high'] - ma['low']).rolling(20).mean()
        ma['atr_pct'] = ma['atr'] / ma['close'] * 100
        avg_atr_pct = ma['atr_pct'].dropna().mean()
        volatility_data.append(('MA', '甲醇', avg_atr_pct, 10, 3000, 0.10))
except Exception as e:
    print(f"读取MA数据失败: {e}")

try:
    ta = pd.read_parquet(f'{data_path}/futures/intraday/TA_2h.parquet')
    if len(ta) > 0:
        ta['atr'] = (ta['high'] - ta['low']).rolling(20).mean()
        ta['atr_pct'] = ta['atr'] / ta['close'] * 100
        avg_atr_pct = ta['atr_pct'].dropna().mean()
        volatility_data.append(('TA', 'PTA', avg_atr_pct, 10, 3000, 0.08))
except Exception as e:
    print(f"读取TA数据失败: {e}")

vol_df = pd.DataFrame(volatility_data, columns=['代码', '名称', '平均ATR%', '合约乘数', '大致保证金', '手续费率'])

print('\n' + '=' * 80)
print('=== 品种波动特性分析 ===')
print('=' * 80)
print(vol_df.to_string(index=False))

print('\n' + '=' * 80)
print('=== 1万元资金适合品种分析 ===')
print('=' * 80)

capital = 10000
risk_per_trade = 100

for idx, row in vol_df.iterrows():
    symbol = row['代码']
    margin = row['大致保证金']
    atr_pct = row['平均ATR%']
    
    max_lots = int(capital / margin)
    
    stop_loss_pct = atr_pct * 1.5
    
    if max_lots > 0:
        contract_value = margin / 0.10
        risk_per_lot = contract_value * (stop_loss_pct / 100)
        lots_to_risk = min(max_lots, int(risk_per_trade / risk_per_lot)) if risk_per_lot > 0 else 0
    else:
        lots_to_risk = 0
    
    suitability = 'AAAAA' if max_lots >= 3 else ('AAAA' if max_lots >= 2 else ('AAA' if max_lots >= 1 else 'AA'))
    
    print(f'\n{row["名称"]} ({symbol}):')
    print(f'  - 平均ATR波动: {atr_pct:.2f}%')
    print(f'  - 大致保证金: {margin}元/手')
    print(f'  - 1万元可交易: {max_lots}手')
    print(f'  - 建议交易手数: {lots_to_risk}手')
    print(f'  - 适合度: {suitability}')

print('\n' + '=' * 80)
print('=== 结论与建议 ===')
print('=' * 80)
print('''
基于1万元资金和单笔100元风险（1%）的限制：

推荐交易品种（按优先级排序）：

1. 螺纹钢 (RB) - 首选
   - 波动适中，ATR约1-2%
   - 保证金约3000元/手
   - 1万元可交易3手
   - 流动性好，交易成本低

2. 白银 (AG) - 次选
   - 波动适中，ATR约1.5-2.5%
   - 保证金约5000元/手
   - 1万元可交易2手
   - 波动性略高，机会更多

3. PTA (TA)
   - 波动较小，ATR约1-1.5%
   - 保证金约3000元/手
   - 1万元可交易3手
   - 适合稳健交易

不建议交易的品种：
- 黄金(AU): 保证金约10000元，1万元只能做1手
- 铁矿石(I): 波动极大，保证金高
- 股指期货(IF/IC/IH): 保证金过高

风控建议：
- 单笔止损：1.5倍ATR（约1.5-3%）
- 日度止损：3%（300元）
- 仓位：最多同时持有2个品种
''')
