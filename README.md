<div align="center"><br><br>
<img src="docs/assets/banner-xicheng.jpg" alt="墨道具箱" width="720"/>
<br><br>

# 墨 道 具 箱
<sub>A I &nbsp;·&nbsp; Q U A N T</sub>
<br>

<sub>― 靜謐而文，案頭之器 ―</sub>

<sub>凡十二器，藏於一函；一令既出，諸具皆備。</sub>
<br>

![](https://img.shields.io/badge/license-MIT-141414?style=flat-square)
![](https://img.shields.io/badge/python-3.10%2B-141414?style=flat-square)
![](https://img.shields.io/badge/strategies-4-141414?style=flat-square)
![](https://img.shields.io/github/stars/LEE20260315/ai-quant-projects?style=flat-square&color=9C2A2A&label=stars)

<br>

<sub><a href="#序">序</a> &nbsp;·&nbsp; <a href="#器">器</a> &nbsp;·&nbsp; <a href="#案">案</a> &nbsp;·&nbsp; <a href="#法">法</a> &nbsp;·&nbsp; <a href="#問">問</a></sub>

<br><br>

<img src="docs/assets/seal-xicheng.png" alt="西城閒人" width="72"/>

<br></div>

---

## 序 <a id="序"></a>

AI量化交易研究項目，整合定價偏差檢測、多因子信號、達爾文權重與雙路徑融合策略。

本項目含兩條技術路徑：路徑一為AI增強系統，專注信號多樣性；路徑二為輕量級分位數系統，追求穩定可靠。

<br>

## 器 <a id="器"></a>

<sub>※ 編號取漢字前導，以求案頭之整齊。</sub>

| 號 | 名 | 用 | 棲 |
|---|---|---|---|
| 〇一 | 定價偏差系統    | 多品套利，跨市場對沖              | Python |
| 〇二 | 四因子信號      | 偏差、動量、均值、回歸、波動率    | Python |
| 〇三 | 達爾文權重      | 動態分配，優勝劣汰                | Python |
| 〇四 | 分位數策略      | 輕量高效，趨勢追蹤                | Python |
| 〇五 | 信號融合引擎    | 雙路徑整合，多維確認              | Python |
| 〇六 | 回測引擎        | 全週期驗證，蒙特卡洛模擬          | Python |
| 〇七 | 實盤追蹤        | 日週追蹤，郵件通知                | Python |

<br>

## 案 <a id="案"></a>

| 客 | 几 | 函 |
|---|---|---|
| 路徑一 AI增強 | Windows / Linux | `path1_ai_enhanced/main.py` |
| 路徑二 輕量級 | Windows / Linux | `path2_lightweight/live_tracker.py` |
| 實盤監控    | Linux          | `path2_lightweight/live_monitor.py` |

<br>

## 法 <a id="法"></a>

```bash
# Clone the repository
git clone https://github.com/LEE20260315/ai-quant-projects.git
cd ai-quant-projects

# Install dependencies
cd path2_lightweight
pip install -r requirements.txt

# Run backtest
python fusion/fusion_backtest.py

# Run live tracker
python live_tracker.py
```

<sub>※ 依賴 pandas、numpy、scipy、akshare 等庫。</sub>

<br>

## 問 <a id="問"></a>

<details>
<summary>雙路徑有何區別？</summary>
<br>
路徑一為AI增強系統，含四因子信號與達爾文權重，強調信號多樣性；路徑二為輕量級分位數系統，追求簡單可靠。
</details>

<details>
<summary>回測表現如何？</summary>
<br>
路徑二表現較穩定，總收益率百分之一百二十一，夏普比率零點七四；路徑一尚在調優中。
</details>

<details>
<summary>是否支持實盤？</summary>
<br>
支持模擬交易追蹤，具備日週報告與郵件通知功能，實盤需自行接入券商API。
</details>

<br>

---

<div align="center">
<img src="docs/assets/seal-xicheng.png" alt="西城閒人" width="64"/>
<br>
<sub>紙承墨，墨載意，意馭器</sub><br>
<sub>西城閒人 · 識</sub><br>
</div>
