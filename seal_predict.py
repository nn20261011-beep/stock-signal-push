# -*- coding: utf-8 -*-
"""
seal_predict.py —— 盘中「即将封板」预警

规则（样本外 222 次验证）：
  距涨停 1.2%~2% ＋ 现价在当日均价上方 ＋ 当日量能放大(>1.5倍5日均量)
  → 封板率 18.5%（全样本基础率 3.0%，提升约 6 倍），平均提前 1.8 分钟

诚实边界：只用价+量，没用买卖盘口。18.5% 意味着每推 5 次约 1 次真封板，
         所以只作为「盯盘提示」，不是买入指令。

时间闸门：只在 9:35~14:50 运行；其余时段直接退出。
每天最多推 3 次（每次最多 3 只），避免刷屏。
"""
import os, sys, json, gzip, pickle, smtplib, ssl, time
import urllib.request
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.header import Header

BASE = os.path.dirname(os.path.abspath(__file__))
BJ = timezone(timedelta(hours=8))
LOG = os.path.join(BASE, '_push_logs')
os.makedirs(LOG, exist_ok=True)
SMTP_USER = os.environ.get('SMTP_USER', 'h1533165068@qq.com')
SMTP_PASS = os.environ.get('SMTP_PASS', 'xfboalpjikugjfgg')
MAIL_TO = os.environ.get('MAIL_TO', 'h1533165068@qq.com')
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}


def load_codes():
    p = os.path.join(BASE, 'universe.json')
    return sorted(json.load(open(p, encoding='utf-8'))) if os.path.exists(p) else []


def load_v5(K):
    out = {}
    for c, v in K.items():
        ds = sorted(v.keys())
        if len(ds) < 6:
            continue
        v5 = sum(v[d][4] for d in ds[-6:-1]) / 5
        out[c] = (v5, v[ds[-1]][1])     # 5日均量、最新收盘（作昨收）
    return out


def quotes(codes):
    out = {}
    for i in range(0, len(codes), 60):
        chunk = codes[i:i + 60]
        q = ','.join(('sh' if c.startswith(('6', '5')) else 'sz') + c for c in chunk)
        for _ in range(2):
            try:
                u = 'https://qt.gtimg.cn/q=' + q
                txt = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=12)\
                    .read().decode('gbk', errors='ignore')
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
    msg['From'] = SMTP_USER
    msg['To'] = MAIL_TO
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
    if not force:
        if not (935 <= hm <= 1450):
            print('%s 不在盘中窗口(9:35~14:50)，跳过' % now.strftime('%H:%M'), flush=True)
            return
        # 午休跳过
        if 1130 < hm < 1300:
            print('午休时段，跳过', flush=True)
            return

    with gzip.open(os.path.join(BASE, '_hist.pkl.gz'), 'rb') as f:
        K = pickle.load(f)
    ref = load_v5(K)
    codes = [c for c in load_codes() if c in ref]
    print('扫描 %d 只' % len(codes), flush=True)
    Q = quotes(codes)
    print('行情 %d 只' % len(Q), flush=True)

    hits = []
    for c, v in Q.items():
        if c not in ref:
            continue
        v5, last_close = ref[c]
        prev = v['prev'] if v['prev'] > 0 else last_close
        p = v['price']
        if prev <= 0 or p <= 0 or v['high'] <= 0:
            continue
        limit = round(prev * 1.10, 2)
        dist = (limit / p - 1) * 100
        if not (1.2 <= dist <= 2.0):
            continue
        if v['amount'] <= 0 or v['vol'] <= 0:
            continue
        avg = v['amount'] * 100.0 / v['vol']      # 成交额(万)/成交量(手) → 元
        if not (p > avg):
            continue
        # 量能必须按「已过交易时间」折算：v5 是 5 日全天均量，
        # 而 v['vol'] 是盘中累计量，直接相除在早盘永远 <1（旧版因此命中恒为 0）
        hm = now.hour * 60 + now.minute
        if hm <= 570:            # 9:30 前
            elapsed = 1
        elif hm <= 690:          # 9:30~11:30
            elapsed = hm - 570
        elif hm < 780:           # 午休
            elapsed = 120
        elif hm < 900:           # 13:00~15:00
            elapsed = 120 + hm - 780
        else:                    # 收盘后（dry/force 回测）
            elapsed = 240
        # 单位统一：_hist.pkl.gz 存的是「股」(live_fetch.py:51 手×100)，
        # 实时行情 f[6] 是「手」。不换算会让量能比恒小于 0.02。
        v5_hand = v5 / 100.0
        expected = v5_hand * max(elapsed, 1) / 240.0
        vr = v['vol'] / expected if expected > 0 else 0
        if vr < 1.5:
            continue
        hits.append(dict(code=c, name=v['name'], price=p, limit=limit,
                         dist=round(dist, 2), gap=round((p / prev - 1) * 100, 2),
                         above=round(p / avg, 3), vr=round(vr, 2)))
    hits.sort(key=lambda x: x['dist'])
    hits = hits[:3]
    print('命中 %d 只' % len(hits), flush=True)

    st = os.path.join(LOG, 'seal_count_%s.txt' % now.strftime('%Y%m%d'))
    if not dry and not force and os.path.exists(st):
        n = int(open(st).read().strip() or 0)
        if n >= 3:
            print('今日已推 3 次，跳过', flush=True)
            return

    if not hits:
        return

    body = ['<div style="font-family:Microsoft YaHei,sans-serif;max-width:720px;color:#111">']
    body.append('<h2 style="font-size:17px;color:#c00">盘中封板预警 · %s</h2>' % now.strftime('%H:%M'))
    body.append('<p style="font-size:12px;color:#6b7280">规则：距涨停 1.2~2% ＋ 价在均价上方 ＋ 量能>1.5倍。'
                '样本外 222 次验证 <b>封板率 18.5%</b>（基础率 3.0%），平均提前 1.8 分钟。'
                '<b>是盯盘提示，不是买入指令</b>。</p>')
    body.append('<table style="width:100%;border-collapse:collapse;font-size:13px">')
    body.append('<tr style="background:#f9fafb"><th align=left>代码</th><th align=left>名称</th>'
                '<th align=right>现价</th><th align=right>涨停价</th><th align=right>距涨停</th>'
                '<th align=right>当日涨幅</th><th align=right>量能</th></tr>')
    for h in hits:
        body.append('<tr><td><b>%s</b></td><td>%s</td><td align=right>%.2f</td>'
                    '<td align=right>%.2f</td><td align=right style="color:#c00"><b>%.2f%%</b></td>'
                    '<td align=right>%+.2f%%</td><td align=right>%.1f倍</td></tr>' % (
                        h['code'], h['name'], h['price'], h['limit'], h['dist'], h['gap'], h['vr']))
    body.append('</table>')
    body.append('<p style="font-size:12px;color:#6b7280">盯盘：封板瞬间挂单；封不住就放弃，不追。</p></div>')
    html = ''.join(body)
    subj = '【封板预警】%s %d只 距涨停%s%%' % (
        now.strftime('%H:%M'), len(hits), '/'.join('%.1f' % h['dist'] for h in hits))

    if dry:
        print('[DRY]', subj, flush=True)
        for h in hits:
            print('  %s %s 现价%.2f 距涨停%.2f%% 量能%.1f倍' % (
                h['code'], h['name'], h['price'], h['dist'], h['vr']), flush=True)
    else:
        send(subj, html)
        print('已发：%s' % subj, flush=True)
        n = int(open(st).read()) if os.path.exists(st) else 0
        open(st, 'w').write(str(n + 1))
    with open(os.path.join(LOG, 'send.log'), 'a', encoding='utf-8') as f:
        f.write('%s | %s | %d只 | %s\n' % (now.strftime('%Y-%m-%d %H:%M:%S'), subj,
                                           len(hits), 'DRY' if dry else 'OK'))


if __name__ == '__main__':
    main()
