<div align="center"><br><br>
<img src="https://raw.githubusercontent.com/LEE20260315/ai-quant-projects/main/docs/assets/banner-xicheng.jpg" alt="AI量化" width="720"/>
<br><br>

# AI 量 化 研 究
<sub>A I &nbsp;·&nbsp; Q U A N T</sub>
<br>

<sub>― 雙路並行，信號融合 ―</sub>

<sub>路徑一求廣，路徑二求精；雙劍合璧，穩中求勝。</sub>
<br>

![](https://img.shields.io/badge/license-MIT-141414?style=flat-square)
![](https://img.shields.io/badge/python-3.10%2B-141414?style=flat-square)
![](https://img.shields.io/badge/strategies-7-141414?style=flat-square)
![](https://img.shields.io/github/stars/LEE20260315/ai-quant-projects?style=flat-square&color=9C2A2A&label=stars)

<br>

<sub><a href="#序">序</a> &nbsp;·&nbsp; <a href="#器">器</a> &nbsp;·&nbsp; <a href="#案">案</a> &nbsp;·&nbsp; <a href="#法">法</a> &nbsp;·&nbsp; <a href="#問">問</a></sub>

<br><br>

<img src="https://raw.githubusercontent.com/LEE20260315/ai-quant-projects/main/docs/assets/seal-xicheng.png" alt="西城閒人" width="72"/>

<br></div>

---

## 序 <a id="序"></a>

本項目為 AI 量化交易研究，整合定價偏差檢測、多因子信號、達爾文權重與雙路徑融合策略，專注中國商品期貨市場。

系統含兩條技術路徑：路徑一為 AI 增強多策略系統，四策略並行、達爾文權重動態分配，強調信號多樣性；路徑二為輕量級分位數系統，簡潔可靠，回測收益率百分之一百二十一、夏普零點七四，已通過六項壓力測試。二者以增強型疊加模式融合，路徑二為主、路徑一輔之。

初始資金一萬元，當前交易 PTA、菜籽粕、甲醇三品。

<br>

## 器 <a id="器"></a>

<sub>※ 編號取漢字前導，以求案頭之整齊。</sub>

| 號 | 名 | 用 | 棲 |
|---|---|---|---|
| 〇一 | 定價偏差信號      | Z-Score 雙重確認，捕捉價格偏離常態     | Python |
| 〇二 | 動量突破信號      | EMA 交叉 + ATR 擴張 + 成交量確認       | Python |
| 〇三 | 均值回歸信號      | 布林帶 + RSI，超買超賣反轉捕捉         | Python |
| 〇四 | 波動率突破信號    | 肯特納通道 + ATR 比率 + 放量確認       | Python |
| 〇五 | 分位數短線策略    | 四十分位 + EMA 趨勢過濾，雙模式切換     | Python |
| 〇六 | 達爾文權重引擎    | Sharpe 勝率回撤加權，動態重平衡         | Python |
| 〇七 | 信號融合器        | 路徑二為主、路徑一增強，同向收緊止損   | Python |

<br>

## 案 <a id="案"></a>

| 客 | 几 | 函 |
|---|---|---|
| 路徑一 回測    | Windows / Linux | `path1_ai_enhanced/main.py` |
| 路徑二 回測    | Windows / Linux | `path2_lightweight/portfolio/portfolio_backtest.py` |
| 融合回測       | Windows / Linux | `path2_lightweight/fusion/fusion_backtest.py` |
| 實盤追蹤       | Windows         | `path2_lightweight/live_tracker.py` |
| 實盤風控監控   | Windows         | `path2_lightweight/live_monitor.py` |
| 週報生成       | Windows         | `path2_lightweight/weekly_report.py` |

<br>

## 法 <a id="法"></a>

```bash
# Clone the repository
git clone https://github.com/LEE20260315/ai-quant-projects.git
cd ai-quant-projects

# Install dependencies
cd path2_lightweight
pip install -r requirements.txt

# Run portfolio backtest
python portfolio/portfolio_backtest.py

# Run fusion backtest
python fusion/fusion_backtest.py

# Run full validation (WF + MC + stress test)
python fusion/full_validation.py

# Start live tracker
python live_tracker.py
```

<sub>※ 依賴 pandas、numpy、akshare、pyarrow 等庫。</sub>

<br>

### 環境變量

```ini
FUTURES_DATA_DIR=/path/to/futures/continuous
```

<sub>※ 數據以 Parquet 格式存於本地，由 AKShare 自動更新。</sub>

<br>

### 前置依賴

| 依 | 所需之器 | 取之之法 |
|---|---|---|
| Python ≥ 3.10 | 全部模組 | `python.org` |
| AKShare | 數據更新 | `pip install akshare` |
| QQ 郵箱 | 日报週報推送 | 配置 SMTP 授權碼 |

<br>

## 問 <a id="問"></a>

<details>
<summary>雙路徑有何區別？</summary>
<br>
路徑一為 AI 增強系統，四策略並行 + 達爾文權重，強調信號多樣性，目前尚在調優中。路徑二為輕量級分位數系統，簡潔可靠，回測夏普零點七四，已通過全部壓力測試，為當前主力策略。
</details>

<details>
<summary>融合模式如何運作？</summary>
<br>
採增強型疊加：路徑二為主信號，路徑一輔助增強。同向一致時收緊止損、縮短持倉；方向衝突時保守處理。融合效果由完整驗證流程評估（Walk-Forward + 蒙特卡羅 + 壓力測試）。
</details>

<details>
<summary>支持哪些品種？</summary>
<br>
當前交易 PTA（TA）、菜籽粕（RM）、甲醇（MA）三品，均為低保證金品種，一萬元可覆蓋。中期規劃擴展至玉米澱粉（CS）、玻璃（FG）、螺紋鋼（RB），長期上限八至十品。
</details>

<details>
<summary>實盤就緒否？</summary>
<br>
實盤追蹤系統已於二〇二六年四月二十三日啟動，處於模擬交易階段。具備日線信號掃描、風控檢查、郵件通知功能。訂單執行為模擬接口，尚未對接真實券商 API。
</details>

<details>
<summary>風控體系如何？</summary>
<br>
三級風控：一級回撤達百分之二十新倉減半，二級達百分之二十七禁止開新倉，三級達百分之三十五全倉平掉。另有最大持倉三品、單品種上限百分之三十、連虧保護等規則。
</details>

<br>

---

<div align="center">
<img src="https://raw.githubusercontent.com/LEE20260315/ai-quant-projects/main/docs/assets/seal-xicheng.png" alt="西城閒人" width="64"/>
<br>
<sub>紙承墨，墨載意，意馭器</sub><br>
<sub>西城閒人 · 識</sub><br>
</div>
