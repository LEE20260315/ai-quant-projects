#!/usr/bin/env python
# -*- coding: utf-8 -*-
import smtplib
import os
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime


def _load_auth_code():
    code = os.environ.get('QQ_MAIL_AUTH_CODE', '')
    if code:
        return code

    config_paths = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tracking', 'email_config.json'),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'email_config.json'),
    ]
    for config_path in config_paths:
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    code = config.get('QQ_MAIL_AUTH_CODE', '')
                    if code:
                        return code
            except (json.JSONDecodeError, IOError):
                pass
    return ''


SMTP_CONFIG = {
    'host': 'smtp.qq.com',
    'port': 465,
    'ssl': True,
    'sender': '78644612@qq.com',
    'auth_code': _load_auth_code(),
}

RECIPIENT = '78644612@qq.com'

EN = 'font-size:11px;color:#999;font-style:italic;margin-left:4px;'


def send_email(subject, html_body, attachments=None):
    if not SMTP_CONFIG['auth_code']:
        config_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tracking')
        print('[MAIL] WARN: QQ_MAIL_AUTH_CODE not found in env var or email_config.json')
        print(f'[MAIL] Create {config_dir}\\email_config.json with: {{"QQ_MAIL_AUTH_CODE": "your_code"}}')
        print('[MAIL] Or set env var: setx QQ_MAIL_AUTH_CODE "your_code"')
        return False

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = SMTP_CONFIG['sender']
    msg['To'] = RECIPIENT
    msg['Date'] = datetime.now().strftime('%a, %d %b %Y %H:%M:%S +0800')

    html_part = MIMEText(html_body, 'html', 'utf-8')
    msg.attach(html_part)

    if attachments:
        for filepath in attachments:
            if not os.path.exists(filepath):
                continue
            with open(filepath, 'rb') as f:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(f.read())
                encoders.encode_base64(part)
                filename = os.path.basename(filepath)
                part.add_header('Content-Disposition', f'attachment; filename="{filename}"')
                msg.attach(part)

    try:
        if SMTP_CONFIG['ssl']:
            server = smtplib.SMTP_SSL(SMTP_CONFIG['host'], SMTP_CONFIG['port'], timeout=30)
        else:
            server = smtplib.SMTP(SMTP_CONFIG['host'], SMTP_CONFIG['port'], timeout=30)
            server.starttls()

        server.login(SMTP_CONFIG['sender'], SMTP_CONFIG['auth_code'])
        server.sendmail(SMTP_CONFIG['sender'], [RECIPIENT], msg.as_string())
        server.quit()
        print(f'[MAIL] OK: sent to {RECIPIENT}')
        return True
    except Exception as e:
        print(f'[MAIL] FAIL: {e}')
        return False


def generate_daily_report_html(report_data):
    date = report_data.get('date', datetime.now().strftime('%Y-%m-%d'))
    account = report_data.get('account', {})
    positions = report_data.get('positions', {})
    signals = report_data.get('signals', [])
    trade_stats = report_data.get('trade_stats', {})
    risk = report_data.get('risk', {})
    version = report_data.get('version', 'v1.2')

    pos_rows = ''
    if positions:
        for sym, pos in positions.items():
            d_cn = '多' if pos.get('direction') == 1 else '空'
            d_en = 'Long' if pos.get('direction') == 1 else 'Short'
            current_price = pos.get('current_price', pos.get('entry_price', 0))
            upnl = pos.get('unrealized_pnl', 0)
            upnl_color = '#27ae60' if upnl >= 0 else '#e74c3c'
            pos_rows += f'''
            <tr>
                <td>{sym}</td>
                <td>{d_cn} <span style="{EN}">({d_en})</span></td>
                <td>{float(pos.get("entry_price", 0)):.0f}</td>
                <td>{current_price:.0f}</td>
                <td style="color:{upnl_color};font-weight:bold;">{upnl:+.0f}</td>
                <td>{pos.get("stop_loss", 0):.0f}</td>
                <td>{pos.get("take_profit", 0):.0f}</td>
                <td>{pos.get("fusion", "none")}</td>
            </tr>'''
    else:
        pos_rows = '<tr><td colspan="8" style="text-align:center;color:#999;">无持仓 <span style="{EN}">(no positions)</span></td></tr>'

    signal_rows = ''
    if signals:
        for s in signals:
            color = '#e74c3c' if s.get('direction') == -1 else '#27ae60'
            d_cn = '多' if s.get('direction') == 1 else '空'
            d_en = 'Long' if s.get('direction') == 1 else 'Short'
            signal_rows += f'''
            <tr>
                <td style="color:{color};font-weight:bold;">{s.get("symbol","")}</td>
                <td>{d_cn} <span style="{EN}">({d_en})</span></td>
                <td>{s.get("pct_rank",0):.3f}</td>
                <td>{s.get("atr",0):.0f}</td>
                <td>{s.get("fusion","none")}</td>
            </tr>'''
    else:
        signal_rows = f'<tr><td colspan="5" style="text-align:center;color:#999;">无信号 <span style="{EN}">(no signals)</span></td></tr>'

    risk_level = risk.get('level', 'normal')
    risk_color = {'normal': '#27ae60', 'level1': '#f39c12', 'level2': '#e67e22', 'level3': '#e74c3c'}.get(risk_level, '#999')
    risk_cn = {'normal': '正常', 'level1': '一级预警', 'level2': '二级预警', 'level3': '三级危险'}.get(risk_level, '正常')
    risk_en = {'normal': 'Normal', 'level1': 'Level 1 Warning', 'level2': 'Level 2 Alert', 'level3': 'Level 3 Danger'}.get(risk_level, 'Normal')

    html = f'''
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Content-Type" content="text/html; charset=utf-8">
<style>
body {{ font-family: "Microsoft YaHei", "PingFang SC", Arial, "Helvetica Neue", sans-serif; background: #f5f5f5; margin: 0; padding: 10px; -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; }}
.container {{ max-width: 700px; margin: 0 auto; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
.header {{ background: linear-gradient(135deg, #2c3e50, #3498db); color: #fff; padding: 18px 24px; }}
.header h1 {{ margin: 0; font-size: 18px; line-height: 1.3; }}
.header .date {{ font-size: 12px; opacity: 0.8; margin-top: 4px; }}
.section {{ padding: 16px 24px; border-bottom: 1px solid #eee; }}
.section h2 {{ font-size: 14px; color: #2c3e50; margin: 0 0 10px 0; padding-bottom: 6px; border-bottom: 2px solid #3498db; }}
table {{ width: 100%; border-collapse: collapse; font-size: 12px; word-break: break-all; }}
th {{ background: #f8f9fa; text-align: left; padding: 6px 8px; color: #555; font-weight: 600; white-space: nowrap; }}
td {{ padding: 6px 8px; border-bottom: 1px solid #f0f0f0; }}
.metrics-row {{ display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 8px; }}
.metric {{ flex: 1; min-width: 140px; padding: 10px 8px; background: #f8f9fa; border-radius: 6px; text-align: center; box-sizing: border-box; }}
.metric .value {{ font-size: 20px; font-weight: bold; color: #2c3e50; line-height: 1.3; }}
.metric .label {{ font-size: 10px; color: #999; margin-top: 2px; line-height: 1.4; }}
.footer {{ padding: 12px 24px; font-size: 10px; color: #999; text-align: center; }}
.table-wrap {{ width: 100%; overflow-x: auto; -webkit-overflow-scrolling: touch; }}

@media screen and (max-width: 480px) {{
  body {{ padding: 4px; }}
  .container {{ border-radius: 4px; }}
  .header {{ padding: 12px 14px; }}
  .header h1 {{ font-size: 15px; }}
  .header .date {{ font-size: 11px; }}
  .section {{ padding: 12px 14px; }}
  .section h2 {{ font-size: 13px; }}
  .metrics-row {{ gap: 4px; }}
  .metric {{ min-width: 100%; padding: 8px 6px; }}
  .metric .value {{ font-size: 18px; }}
  .metric .label {{ font-size: 9px; }}
  table {{ font-size: 11px; }}
  th {{ padding: 4px 5px; font-size: 10px; }}
  td {{ padding: 4px 5px; font-size: 11px; }}
  .footer {{ padding: 10px 14px; font-size: 9px; }}
}}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>量化融合日报 <span style="font-size:13px;font-style:italic;opacity:0.8;">(QuantFusion Daily)</span></h1>
        <div class="date">{date} | {version}</div>
    </div>

    <div class="section">
        <h2>账户概览 <span style="{EN}">(Account Overview)</span></h2>
        <div class="metrics-row">
            <div class="metric"><div class="value">{account.get("total_equity",account.get("capital",0)):,.0f}</div><div class="label">账户权益<br><span style="{EN}">(Total Equity)</span></div></div>
            <div class="metric"><div class="value" style="color:{'#27ae60' if account.get('total_return_pct',0)>=0 else '#e74c3c'}">{account.get("total_return_pct",0):+.1f}%</div><div class="label">累计收益<br><span style="{EN}">(Return)</span></div></div>
            <div class="metric"><div class="value" style="color:{'#27ae60' if account.get('drawdown_pct',0)<20 else '#e74c3c'}">{account.get("drawdown_pct",0):.1f}%</div><div class="label">当前回撤<br><span style="{EN}">(Drawdown)</span></div></div>
        </div>
        <div class="metrics-row">
            <div class="metric" style="background:#f0f7ff;"><div class="value">{account.get("capital",0):,.0f}</div><div class="label">已实现资金<br><span style="{EN}">(Realized)</span></div></div>
            <div class="metric" style="background:{'#e8f8e8' if account.get('unrealized_pnl',0)>=0 else '#fde8e8'};"><div class="value" style="color:{'#27ae60' if account.get('unrealized_pnl',0)>=0 else '#e74c3c'}">{account.get("unrealized_pnl",0):+,.0f}</div><div class="label">浮动盈亏<br><span style="{EN}">(Unrealized)</span></div></div>
        </div>
    </div>

    <div class="section">
        <h2>当前持仓 <span style="{EN}">(Open Positions)</span></h2>
        <div class="table-wrap">
        <table>
            <tr><th>品种</th><th>方向</th><th>入场</th><th>现价</th><th>浮盈</th><th>止损</th><th>止盈</th><th>融合</th></tr>
            {pos_rows}
        </table>
        </div>
    </div>

    <div class="section">
        <h2>信号扫描 <span style="{EN}">(Signal Scan)</span></h2>
        <div class="table-wrap">
        <table>
            <tr><th>品种</th><th>方向</th><th>分位排名</th><th>ATR</th><th>融合</th></tr>
            {signal_rows}
        </table>
        </div>
    </div>

    <div class="section">
        <h2>风控状态 <span style="{EN}">(Risk Control)</span></h2>
        <div style="padding:8px 12px;background:{risk_color}22;border-left:4px solid {risk_color};border-radius:4px;">
            <span style="color:{risk_color};font-weight:bold;">[{risk_cn}]</span>
            <span style="{EN}">({risk_en})</span>
            <span style="color:#555;"> - {risk.get('message','')}</span>
        </div>
    </div>

    <div class="section">
        <h2>交易统计 <span style="{EN}">(Trade Stats)</span></h2>
        <div class="metrics-row">
            <div class="metric"><div class="value">{trade_stats.get("total_trades",0)}</div><div class="label">总交易数<br><span style="{EN}">(Total Trades)</span></div></div>
            <div class="metric"><div class="value">{trade_stats.get("win_rate",0):.0f}%</div><div class="label">胜率<br><span style="{EN}">(Win Rate)</span></div></div>
            <div class="metric"><div class="value">{trade_stats.get("avg_pnl",0):+.0f}</div><div class="label">平均盈亏<br><span style="{EN}">(Avg PnL)</span></div></div>
        </div>
    </div>

    <div class="footer">
        量化融合系统 v1.2 | 自动生成 <span style="font-style:italic;">(Auto-generated)</span> | {datetime.now().strftime('%Y-%m-%d %H:%M')}
    </div>
</div>
</body>
</html>'''
    return html


def generate_weekly_report_html(week_data):
    week_start = week_data.get('week_start', '')
    week_end = week_data.get('week_end', '')
    daily_summaries = week_data.get('daily_summaries', [])
    trade_log = week_data.get('trade_log', [])
    key_findings = week_data.get('key_findings', [])
    trend_analysis = week_data.get('trend_analysis', {})
    suggestions = week_data.get('suggestions', [])

    daily_rows = ''
    for d in daily_summaries:
        ret_color = '#27ae60' if d.get('return_pct', 0) >= 0 else '#e74c3c'
        daily_rows += f'''
        <tr>
            <td>{d.get("date","")}</td>
            <td>{d.get("capital",0):,.0f}</td>
            <td style="color:{ret_color}">{d.get("return_pct",0):+.1f}%</td>
            <td>{d.get("drawdown",0):.1f}%</td>
            <td>{d.get("positions",0)}</td>
            <td>{d.get("signals","")}</td>
        </tr>'''

    trade_rows = ''
    if trade_log:
        for t in trade_log:
            pnl_color = '#27ae60' if t.get('pnl', 0) >= 0 else '#e74c3c'
            d_cn = '多' if t.get('direction') == 'long' else '空'
            trade_rows += f'''
            <tr>
                <td>{t.get("symbol","")}</td>
                <td>{d_cn}</td>
                <td>{t.get("entry_date","")}</td>
                <td>{t.get("exit_date","")}</td>
                <td style="color:{pnl_color};font-weight:bold;">{t.get("pnl",0):+.0f}</td>
                <td>{t.get("exit_reason","")}</td>
            </tr>'''
    else:
        trade_rows = f'<tr><td colspan="6" style="text-align:center;color:#999;">本周无交易 <span style="{EN}">(no trades this week)</span></td></tr>'

    finding_items = ''
    for i, f in enumerate(key_findings, 1):
        priority_color = {'high': '#e74c3c', 'medium': '#f39c12', 'low': '#27ae60'}.get(f.get('priority', 'low'), '#999')
        priority_cn = {'high': '高', 'medium': '中', 'low': '低'}.get(f.get('priority', 'low'), '低')
        priority_en = f.get('priority', 'low').upper()
        finding_items += f'''
        <div style="margin:8px 0;padding:8px 12px;background:#f8f9fa;border-radius:4px;border-left:3px solid {priority_color};">
            <strong>[{priority_cn}]</strong> <span style="{EN}">({priority_en})</span> {f.get("text","")}
        </div>'''

    suggestion_items = ''
    for i, s in enumerate(suggestions, 1):
        effort_cn = {'low': '低', 'medium': '中', 'high': '高', 'none': '无'}.get(s.get('effort', ''), s.get('effort', ''))
        suggestion_items += f'''
        <div style="margin:8px 0;padding:8px 12px;background:#eaf6ff;border-radius:4px;border-left:3px solid #3498db;">
            <strong>P{i}</strong> {s.get("text","")}
            <span style="color:#999;font-size:11px;"> 难度:{effort_cn} <span style="{EN}">({s.get("effort","")})</span></span>
        </div>'''

    trend = trend_analysis
    signal_freq = trend.get('signal_freq', 'N/A')
    market_regime = trend.get('market_regime', 'N/A')
    regime_cn = {'Uptrend': '上升趋势', 'Downtrend': '下降趋势', 'Range-bound': '震荡行情'}.get(market_regime, market_regime)
    health = trend.get('health', 'N/A')
    health_cn = {'good': '良好', 'stable': '稳定', 'caution': '需关注', 'danger': '危险'}.get(health, health)
    health_color = '#27ae60' if health in ('good', 'stable') else '#e74c3c'

    trend_section = f'''
    <div class="trend-row">
        <div class="trend-card">
            <div style="font-size:10px;color:#999;">信号频率 <span style="{EN}">(Signal Freq)</span></div>
            <div style="font-size:16px;font-weight:bold;color:#2c3e50;margin-top:4px;">{signal_freq}</div>
        </div>
        <div class="trend-card">
            <div style="font-size:10px;color:#999;">市场状态 <span style="{EN}">(Regime)</span></div>
            <div style="font-size:16px;font-weight:bold;color:#2c3e50;margin-top:4px;">{regime_cn} <span style="{EN}">({market_regime})</span></div>
        </div>
        <div class="trend-card">
            <div style="font-size:10px;color:#999;">策略健康度 <span style="{EN}">(Health)</span></div>
            <div style="font-size:16px;font-weight:bold;color:{health_color};margin-top:4px;">{health_cn} <span style="{EN}">({health})</span></div>
        </div>
    </div>'''

    html = f'''
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Content-Type" content="text/html; charset=utf-8">
<style>
body {{ font-family: "Microsoft YaHei", "PingFang SC", Arial, "Helvetica Neue", sans-serif; background: #f5f5f5; margin: 0; padding: 10px; -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; }}
.container {{ max-width: 750px; margin: 0 auto; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
.header {{ background: linear-gradient(135deg, #1a5276, #2980b9); color: #fff; padding: 20px 24px; }}
.header h1 {{ margin: 0; font-size: 19px; line-height: 1.3; }}
.header .date {{ font-size: 12px; opacity: 0.8; margin-top: 4px; }}
.section {{ padding: 16px 24px; border-bottom: 1px solid #eee; }}
.section h2 {{ font-size: 14px; color: #2c3e50; margin: 0 0 10px 0; padding-bottom: 6px; border-bottom: 2px solid #2980b9; }}
table {{ width: 100%; border-collapse: collapse; font-size: 12px; word-break: break-all; }}
th {{ background: #f8f9fa; text-align: left; padding: 6px 8px; color: #555; font-weight: 600; white-space: nowrap; }}
td {{ padding: 6px 8px; border-bottom: 1px solid #f0f0f0; }}
.footer {{ padding: 12px 24px; font-size: 10px; color: #999; text-align: center; }}
.table-wrap {{ width: 100%; overflow-x: auto; -webkit-overflow-scrolling: touch; }}
.finding {{ margin: 6px 0; padding: 8px 12px; background: #f8f9fa; border-radius: 4px; border-left: 3px solid #ccc; font-size: 13px; }}
.suggestion {{ margin: 6px 0; padding: 8px 12px; background: #eaf6ff; border-radius: 4px; border-left: 3px solid #3498db; font-size: 13px; }}
.trend-card {{ flex: 1; min-width: 180px; padding: 10px 8px; background: #f8f9fa; border-radius: 6px; text-align: center; }}
.trend-row {{ display: flex; flex-wrap: wrap; gap: 8px; }}

@media screen and (max-width: 480px) {{
  body {{ padding: 4px; }}
  .container {{ border-radius: 4px; }}
  .header {{ padding: 12px 14px; }}
  .header h1 {{ font-size: 15px; }}
  .header .date {{ font-size: 11px; }}
  .section {{ padding: 12px 14px; }}
  .section h2 {{ font-size: 13px; }}
  .trend-row {{ gap: 4px; }}
  .trend-card {{ min-width: 100%; padding: 8px 6px; }}
  table {{ font-size: 11px; }}
  th {{ padding: 4px 5px; font-size: 10px; }}
  td {{ padding: 4px 5px; font-size: 11px; }}
  .finding {{ font-size: 12px; }}
  .suggestion {{ font-size: 12px; }}
  .footer {{ padding: 10px 14px; font-size: 9px; }}
}}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>量化融合周报 <span style="font-size:14px;font-style:italic;opacity:0.8;">(QuantFusion Weekly)</span></h1>
        <div class="date">{week_start} ~ {week_end}</div>
    </div>

    <div class="section">
        <h2>趋势分析 <span style="{EN}">(Trend Analysis)</span></h2>
        {trend_section}
    </div>

    <div class="section">
        <h2>关键发现 <span style="{EN}">(Key Findings)</span></h2>
        {finding_items if finding_items else f'<div style="color:#999;padding:8px;font-size:13px;">本周无关键发现 <span style="{EN}">(No key findings)</span></div>'}
    </div>

    <div class="section">
        <h2>每日汇总 <span style="{EN}">(Daily Summary)</span></h2>
        <div class="table-wrap">
        <table>
            <tr><th>日期</th><th>资金</th><th>收益</th><th>回撤</th><th>持仓</th><th>信号</th></tr>
            {daily_rows}
        </table>
        </div>
    </div>

    <div class="section">
        <h2>本周交易 <span style="{EN}">(Weekly Trades)</span></h2>
        <div class="table-wrap">
        <table>
            <tr><th>品种</th><th>方向</th><th>入场</th><th>出场</th><th>盈亏</th><th>原因</th></tr>
            {trade_rows}
        </table>
        </div>
    </div>

    <div class="section">
        <h2>优化建议 <span style="{EN}">(Suggestions)</span></h2>
        {suggestion_items if suggestion_items else f'<div style="color:#999;padding:8px;font-size:13px;">本周无优化建议 <span style="{EN}">(No suggestions)</span></div>'}
    </div>

    <div class="footer">
        量化融合系统 v1.2 | 自动生成周报 <span style="font-style:italic;">(Weekly auto-report)</span> | {datetime.now().strftime('%Y-%m-%d %H:%M')}
    </div>
</div>
</body>
</html>'''
    return html
