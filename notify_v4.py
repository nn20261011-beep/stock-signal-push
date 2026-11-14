# -*- coding: utf-8 -*-
"""notify_v4.py —— 把 system_v4 的决策发成邮件"""
import os, sys, json, smtplib, ssl, gzip, pickle
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.header import Header

BASE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(BASE, '_push_logs')
BJ = timezone(timedelta(hours=8))
SMTP_USER = os.environ.get('SMTP_USER', 'h1533165068@qq.com')
SMTP_PASS = os.environ.get('SMTP_PASS', 'xfboalpjikugjfgg')
MAIL_TO = os.environ.get('MAIL_TO', 'h1533165068@qq.com')

SELL_TXT = {'sl5': '跌5%止损/上限10日', 'sl8': '跌8%止损/上限10日',
            'rbreak': '断板次日走', 'r10': '持满10日', 'r5': '持满5日',
            'r3': '持满3日', 'tp8': '涨8%止盈', 'tp5': '涨5%止盈',
            'ma5_n': '跌破MA5走', 'ma10_n': '跌破MA10走'}


def send(subject, html):
    msg = MIMEText(html, 'html', 'utf-8')
    msg['From'], msg['To'] = SMTP_USER, MAIL_TO
    msg['Subject'] = Header(subject, 'utf-8')
    s = smtplib.SMTP_SSL('smtp.qq.com', 465, timeout=25,
                         context=ssl.create_default_context())
    s.login(SMTP_USER, SMTP_PASS)
    s.sendmail(SMTP_USER, [MAIL_TO], msg.as_string())
    s.quit()


def main():
    dry = '--dry' in sys.argv
    now = datetime.now(BJ)
    fp = os.path.join(LOG, 'decision_%s.json' % now.strftime('%Y%m%d'))
    if not os.path.exists(fp):
        cand = sorted([f for f in os.listdir(LOG) if f.startswith('decision_')])
        if not cand:
            print('无决策文件，跳过', flush=True)
            return
        fp = os.path.join(LOG, cand[-1])
    d = json.load(open(fp, encoding='utf-8'))
    picks = d.get('picks') or []
    body = ['<div style="font-family:Microsoft YaHei,sans-serif;max-width:760px;color:#111">']
    body.append('<h2 style="font-size:18px">%s 收盘决策 · 七层模式 v4</h2>' % d.get('day', ''))
    body.append('<p style="font-size:12px;color:#6b7280">生成时间 %s ｜ 判天：%s ｜ 动作：%s</p>' % (
        now.strftime('%Y-%m-%d %H:%M'), d.get('stage', ''), d.get('action', '')))
    body.append('<p style="font-size:13px;background:#eef2ff;padding:8px;border-radius:6px">'
                '<b>判天依据</b>：%s</p>' % d.get('reason', ''))
    if d.get('blocks'):
        body.append('<p style="font-size:13px;background:#fef2f2;padding:8px;color:#b91c1c">'
                    '<b>纪律拦截</b>：%s</p>' % '；'.join(d['blocks']))
    if not picks:
        body.append('<p style="font-size:15px;color:#b91c1c"><b>今日空仓</b>，不推任何标的。</p>')
    else:
        body.append('<p style="font-size:13px">共 <b>%d</b> 只，单票上限 <b>%.0f%%</b>，'
                    '最多同时 %d 只。买入口径：次日竞价确认后按开盘价买入（低开/高开>7%% 放弃）。</p>' % (
                        len(picks), float(d.get('max_weight', 0)) * 100, int(d.get('max_picks', 0))))
        body.append('<table style="width:100%;border-collapse:collapse;font-size:13px">')
        body.append('<tr style="background:#f9fafb"><th align=left>代码</th><th align=left>票类</th>'
                    '<th align=right>今收</th><th align=left>理由</th><th align=right>权重</th>'
                    '<th align=left>卖点</th></tr>')
        for x in picks:
            body.append('<tr><td><b>%s</b></td><td>%s</td><td align=right>%.2f</td>'
                        '<td style="font-size:11px">%s</td><td align=right>%.0f%%</td>'
                        '<td style="font-size:12px">%s</td></tr>' % (
                            x['code'], x['type'], float(x['close']), x['why'],
                            float(x['weight']) * 100, SELL_TXT.get(x['sell'], x['sell'])))
        body.append('</table>')
    body.append('<p style="font-size:12px;color:#6b7280;margin-top:12px">'
                '七层模式：心法十条 → 判天五阶段 → 四类票 → 三买四卖 → 赢面分档 → 纪律熔断 → 复盘降档。'
                '心法红线逐条机检，未通过的不出现在本表。</p></div>')
    html = ''.join(body)
    subj = '【决策 v4】%s %s · %s %d只' % (
        d.get('day', ''), d.get('stage', ''), d.get('action', ''), len(picks))
    if dry:
        print('[DRY]', subj, flush=True)
        for x in picks:
            print('  %s %-4s %.0f%% %s' % (x['code'], x['type'], float(x['weight']) * 100, x['why']), flush=True)
    else:
        send(subj, html)
        print('已发：%s' % subj, flush=True)
    with open(os.path.join(LOG, 'send.log'), 'a', encoding='utf-8') as f:
        f.write('%s | %s | %d只 | %s\n' % (now.strftime('%Y-%m-%d %H:%M:%S'), subj,
                                           len(picks), 'DRY' if dry else 'OK'))


if __name__ == '__main__':
    main()
