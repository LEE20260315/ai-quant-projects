from data.parquet_loader import ParquetLoader
l = ParquetLoader()
for sym in ['MA', 'RM', 'TA', 'M']:
    df = l.load_symbol(sym, '2010-01-01', '2025-12-31')
    if df is not None and len(df) > 0:
        print(f"{sym}: {len(df)} rows, {df['date'].iloc[0]} ~ {df['date'].iloc[-1]}")
    else:
        print(f"{sym}: NO DATA")
