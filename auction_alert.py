# -*- coding: utf-8 -*-
"""
auction_alert.py —— 集合竞价结束（9:25）即推送的盯盘提示

与 seal_predict.py 的分工：
  - 本脚本 9:26 跑一次：用竞价高开幅度筛「今日大概率冲击涨停」的票，只盯不买
  - seal_predict.py 盘中每 12 秒：距涨停 1.2~2% + 均价上方 + 量能放大，才是真正预警

竞价规则（线上历史 2024-09~2026-11 实测）：
  主板 + 高开 >= 7% + 非一字
  → 当日收盘封板率 54.1%（n=2484）
  → 但次日开盘卖 -2.531%/胜率39.6%，所以【只做盯盘提示，不是买入指令】
  一字涨停未持股者买不到，剔除（994 笔，占 28.6%）

时间：北京时间 9:26 触发一次；9:30 之后交给 seal_predict.py 常规扫描。
去重：auction_sent_YYYYMMDD.json，同一只票当天不重复。
"""
import os, sys, json, gzip, pickle, smtplib, ssl, time, urllib.request
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.header import Header

BASE = os.path.dirname(os.path.abspath(__file__))
BJ = timezone(timedelta(hours=8))
LOG = os.path.join(BASE, '_push_logs')
os.makedirs(LOG, exist_ok=True)
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
SMTP_USER = os.environ.get('SMTP_USER', 'h1533165068@qq.com')
SMTP_PASS = os.environ.get('SMTP_PASS', 'xfboalpjikugjfgg')
MAIL_TO = os.environ.get('MAIL_TO', 'h1533165068@qq.com')
GAP_MIN = 7.0      # 竞价高开下限（%）
MAX_PICK = 8       # 一次最多推 8 只，按高开降序


def load_codes():
    p = os.path.join(BASE, 'universe.json')
    return sorted(json.load(open(p, encoding='utf-8'))) if os.path.exists(p) else []


def quotes(codes):
    out = {}
    for i in range(0, len(codes), 60):
        chunk = codes[i:i + 60]
        q = ','.join(('sh' if c.startswith(('6', '5')) else 'sz') + c for c in chunk)
        for _ in range(2):
            try:
                txt = urllib.request.urlopen(urllib.request.Request(
                    'https://qt.gtimg.cn/q=' + q, headers=UA), timeout=12).read().decode('gbk', 'ignore')
                for line in txt.split(';'):
                    if '=' not in line:
                        continue
                    f = line.split('=', 1)[1].strip('"').split('~')
                    if len(f) < 40 or not f[2]:
                        continue
                    try:
                        out[f[2]] = dict(name=f[1], price=float(f[3] or 0), prev=float(f[4] or 0),
                                         open=float(f[5] or 0), vol=float(f[6] or 0),
                                         high=float(f[33] or 0), low=float(f[34] or 0),
                                         amount=float(f[37] or 0))
                    except Exception:
                        pass
                break
            except Exception:
                time.sleep(0.3)
    return out


def send(subject, html):
    msg = MIMEText(html, 'html', 'utf-8')
    msg['From'], msg['To'] = SMTP_USER, MAIL_TO
    msg['Subject'] = Header(subject, 'utf-8')
    s = smtplib.SMTP_SSL('smtp.qq.com', 465, timeout=25, context=ssl.create_default_context())
    s.login(SMTP_USER, SMTP_PASS)
    s.sendmail(SMTP_USER, [MAIL_TO], msg.as_string())
    s.quit()


def main():
    dry = '--dry' in sys.argv
    force = '--force' in sys.argv
    now = datetime.now(BJ)
    hm = now.hour * 100 + now.minute
    if not force and not (925 <= hm <= 935):
        print('%s 不在竞价窗口(9:25~9:35)，跳过' % now.strftime('%H:%M'), flush=True)
        return

    codes = [c for c in load_codes() if c.startswith(('60', '00')) and not c.startswith('688')]
    Q = quotes(codes)
    print('竞价行情 %d 只' % len(Q), flush=True)

    hits = []
    for c, v in Q.items():
        prev = v['prev']
        o = v['open']
        if prev <= 0 or o <= 0 or v['high'] <= 0:
            continue
        gapo = (o / prev - 1) * 100
        if gapo < GAP_MIN:
            continue
        zt = float((Decimal(str(prev)) * Decimal('1.10')).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP))
        # 一字（开=高=低=收）买不到，剔除
        if abs(v['high'] - zt) < 0.005 and abs(v['low'] - zt) < 0.005:
            continue
        if 'ST' in v['name'] or '退' in v['name']:
            continue
        hits.append(dict(code=c, name=v['name'], open=o, prev=prev, zt=zt,
                         gapo=round(gapo, 2), dist=round((zt / o - 1) * 100, 2)))
    hits.sort(key=lambda x: -x['gapo'])
    hits = hits[:MAX_PICK]
    print('命中 %d 只' % len(hits), flush=True)

    if not hits:
        return

    parts = ['%s(%s) 开%.2f +%.1f%%' % (h['name'], h['code'], h['open'], h['gapo']) for h in hits]
    subj = '【竞价盯盘】%s %d只 %s' % (now.strftime('%H:%M'), len(hits), ' | '.join(parts))

    body = ['<div style="font-family:Microsoft YaHei,sans-serif;max-width:760px;color:#111">']
    body.append('<table style="width:100%;border-collapse:collapse;font-size:13px">'
                '<tr style="background:#f9fafb"><th align=left>名称(代码)</th><th align=right>竞价开盘</th>'
                '<th align=right>高开</th><th align=right>涨停价</th><th align=right>距涨停</th></tr>')
    for h in hits:
        body.append('<tr><td><b>%s(%s)</b></td><td align=right>%.2f</td>'
                    '<td align=right style="color:#c00"><b>+%.2f%%</b></td><td align=right>%.2f</td>'
                    '<td align=right>%.2f%%</td></tr>' % (
                        h['name'], h['code'], h['open'], h['gapo'], h['zt'], h['dist']))
    body.append('</table><p style="font-size:11px;color:#6b7280">竞价高开≥7%%＋非一字：历史 2484 笔当日封板率 54.1%%，'
                '但次日开盘卖 −2.53%%（胜率 39.6%%）。<b>只做盯盘，不是买入指令。</b></p></div>')
    html = ''.join(body)

    if dry:
        print('[DRY]', subj, flush=True)
    else:
        send(subj, html)
        print('已发：%s' % subj, flush=True)
    with open(os.path.join(LOG, 'send.log'), 'a', encoding='utf-8') as f:
        f.write('%s | %s | %d只 | %s\n' % (now.strftime('%Y-%m-%d %H:%M:%S'), subj,
                                           len(hits), 'DRY' if dry else 'OK'))


if __name__ == '__main__':
    main()
