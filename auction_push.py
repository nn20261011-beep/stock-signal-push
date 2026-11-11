# -*- coding: utf-8 -*-
"""
auction_push.py —— 一进二低开打法 · 两段式推送

为什么两段：
  你的操作条件是「手机、9:25 竞价结束后 5 分钟内下单」。
  所以前一晚给候选池（不用决策），9:25 给确认名单（直接照做）。

模式：
  python auction_push.py scan      前一晚 20:00：从今日首板筛候选池
  python auction_push.py confirm   次日 09:25:40：用竞价开盘价算低开幅度，出确认名单

策略（回测 2016-2026，3188 笔，11/11 年正）：
  买：T日首板 → T+1 竞价低开 -7%~-3% → 开盘价买入
  卖：涨停继续持有；不涨停当天收盘走
  止损：8%（几乎不触发，仅防黑天鹅）
"""
import os, sys, json, pickle, smtplib, ssl, glob, time
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.header import Header

BASE = os.path.dirname(os.path.abspath(__file__))
BJ = timezone(timedelta(hours=8))
LOG = os.path.join(BASE, '_auction_logs')
os.makedirs(LOG, exist_ok=True)
SMTP_USER = os.environ.get('SMTP_USER', 'h1533165068@qq.com')
SMTP_PASS = os.environ.get('SMTP_PASS', 'xfboalpjikugjfgg')
MAIL_TO = os.environ.get('MAIL_TO', 'h1533165068@qq.com')

ZT_LO, ZT_HI = 9.8, 10.6
LOW_LO, LOW_HI = -7.0, -3.0     # 命中区间：次日开盘跌幅


def get_codes():
    p = os.path.join(BASE, 'universe.json')
    if os.path.exists(p):
        return sorted(json.load(open(p, encoding='utf-8')))
    return sorted({os.path.basename(f).replace('.pkl', '')
                   for f in glob.glob(os.path.join(BASE, '_kline_raw', '*.pkl'))})


def http(url, enc='gbk', timeout=15):
    import urllib.request
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    return urllib.request.urlopen(req, timeout=timeout).read().decode(enc, errors='ignore')


def quotes(codes):
    """腾讯批量行情，返回 code -> {name, open, prev, price, high, low, vol}"""
    out = {}
    def one(chunk):
        q = ','.join(('sh' if c.startswith(('6', '5')) else 'sz') + c for c in chunk)
        for _ in range(2):
            try:
                txt = http('https://qt.gtimg.cn/q=' + q)
                r = {}
                for line in txt.split(';'):
                    if '=' not in line:
                        continue
                    f = line.split('=', 1)[1].strip('"').split('~')
                    if len(f) < 40 or not f[2]:
                        continue
                    try:
                        r[f[2]] = dict(name=f[1], open=float(f[5] or 0), prev=float(f[4] or 0),
                                       price=float(f[3] or 0), high=float(f[33] or 0),
                                       low=float(f[34] or 0), vol=float(f[6] or 0) * 100)
                    except Exception:
                        pass
                return r
            except Exception:
                time.sleep(0.3)
        return {}
    from concurrent.futures import ThreadPoolExecutor, as_completed
    chunks = [codes[i:i + 60] for i in range(0, len(codes), 60)]
    with ThreadPoolExecutor(max_workers=8) as ex:
        for f in as_completed([ex.submit(one, c) for c in chunks]):
            out.update(f.result())
    return out


def kline_today(code):
    """新浪日线最后 80 根（含今日，用于算首板特征）"""
    sym = ('sh' if code.startswith(('6', '5')) else 'sz') + code
    u = ('https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketData.getKLineData'
         '?symbol=%s&scale=240&ma=no&datalen=80' % sym)
    for _ in range(2):
        try:
            a = json.loads(http(u, 'utf-8', 12))
            return [(x['day'][:10], float(x['open']), float(x['close']),
                     float(x['high']), float(x['low']), float(x['volume'])) for x in a]
        except Exception:
            time.sleep(0.25)
    return []


def send(subject, html):
    msg = MIMEText(html, 'html', 'utf-8')
    msg['From'] = SMTP_USER; msg['To'] = MAIL_TO
    msg['Subject'] = Header(subject, 'utf-8')
    s = smtplib.SMTP_SSL('smtp.qq.com', 465, timeout=25, context=ssl.create_default_context())
    s.login(SMTP_USER, SMTP_PASS)
    s.sendmail(SMTP_USER, [MAIL_TO], msg.as_string())
    s.quit()


# ---------------- scan：前一晚筛候选池 ----------------
def do_scan(dry=False):
    ind = json.load(open(os.path.join(BASE, '_industry_all.json'), encoding='utf-8'))
    ind_of = {c: (v.get('ind2') or 'OTHER') for c, v in ind.items()}
    fcap_of = {c: (v.get('fcap') or 0) / 1e8 for c, v in ind.items()}
    name_of = {c: (v.get('name') or '') for c, v in ind.items()}
    codes = [c for c in get_codes()
             if not ('ST' in name_of.get(c, '') or '退' in name_of.get(c, ''))]
    print('扫描 %d 只（首板筛选）' % len(codes), flush=True)
    q = quotes(codes)
    rows = []
    from concurrent.futures import ThreadPoolExecutor, as_completed
    def one(c):
        k = kline_today(c)
        if len(k) < 30:
            return None
        d, o, cl, hi, lo, v = k[-1]
        pc = k[-2][2]
        if pc <= 0:
            return None
        chg = (cl / pc - 1) * 100
        if not (ZT_LO <= chg <= ZT_HI):
            return None
        # 一字板排除（开盘即涨停且最低=涨停）
        if o >= round(pc * 1.10, 2) - 0.011 and lo >= round(pc * 1.10, 2) - 0.011:
            return None
        C = np.array([x[2] for x in k], float)
        V = np.array([x[5] for x in k], float)
        H = np.array([x[3] for x in k], float)
        L = np.array([x[4] for x in k], float)
        amp = (hi - lo) / pc * 100
        v5 = float(np.mean(V[-6:-1]))
        volx = V[-1] / v5 if v5 > 0 else np.nan
        p60 = float((C[-60:] < cl).sum()) / 60 * 100
        dd250 = (cl / float(np.max(H[-250:]))) * 100 - 100 if len(H) >= 60 else np.nan
        return dict(code=c, name=name_of.get(c, ''), close=round(cl, 2), chg=round(chg, 2),
                    amp=round(amp, 2), vol_x=round(volx, 2) if not np.isnan(volx) else None,
                    p60=round(p60, 0), dd250=round(dd250, 1) if not np.isnan(dd250) else None,
                    fmc=round(fcap_of.get(c, 0), 1), ind2=ind_of.get(c, 'OTHER'),
                    day=d)
    with ThreadPoolExecutor(max_workers=12) as ex:
        for f in as_completed([ex.submit(one, c) for c in codes]):
            r = f.result()
            if r:
                rows.append(r)
    P = pd.DataFrame(rows)
    if not len(P):
        print('今日无首板')
        return
    # 候选：首板 + 剔除次新/高价/超大盘（游资口径，均已在我的数据里验证过方向）
    cand = P[(P['price'] if 'price' in P else P['close']) > 0].copy()
    cand['price'] = cand['close']
    cand = cand[cand['price'] < 40]
    cand = cand[cand['fmc'] < 200]
    cand = cand.sort_values('amp', ascending=False)   # 振幅大=分歧充分，优先
    print('首板 %d 只，候选 %d 只' % (len(P), len(cand)))
    cand.to_csv(os.path.join(LOG, 'cand_%s.csv' % P['day'].iloc[0]), index=False, encoding='utf-8-sig')
    json.dump(dict(day=P['day'].iloc[0], cand=cand.to_dict('records')),
              open(os.path.join(LOG, 'cand_latest.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    # 邮件
    body = ['<div style="font-family:Microsoft YaHei,sans-serif;max-width:720px">']
    body.append('<h2 style="font-size:17px">明日一进二候选池 · 基准日 %s</h2>' % P['day'].iloc[0])
    body.append('<p style="font-size:13px;color:#555">共 <b>%d</b> 只首板。'
                '<b>明天 9:25 竞价结束后</b>，我只对<b>低开 -7%%~-3%%</b> 的票发确认名单；'
                '没进区间的不买。</p>' % len(cand))
    body.append('<table style="width:100%;border-collapse:collapse;font-size:13px">')
    body.append('<tr style="background:#f9fafb"><th align=left>代码</th><th align=left>名称</th>'
                '<th align=right>今收</th><th align=right>振幅</th><th align=right>距高</th>'
                '<th align=right>分位</th><th align=left>行业</th></tr>')
    for _, r in cand.head(20).iterrows():
        body.append('<tr><td>%s</td><td>%s</td><td align=right>%.2f</td><td align=right>%.1f%%</td>'
                    '<td align=right>%s</td><td align=right>%.0f</td><td>%s</td></tr>' % (
                        r['code'], r['name'], r['close'], r['amp'],
                        ('%.1f%%' % r['dd250']) if r['dd250'] is not None else '-',
                        r['p60'], r['ind2']))
    body.append('</table>')
    body.append('<p style="font-size:12px;color:#6b7280">回测：2016–2026 共 3188 笔，'
                '次日低开 -7%%~-3%% 买入，笔均 +1.05%%，胜率 52.5%%，平均持有 1.1 天，11/11 年正。</p>')
    html = ''.join(body)
    subj = '【明日候选】%s 首板 %d 只 · 等竞价低开确认' % (P['day'].iloc[0], len(cand))
    open(os.path.join(LOG, 'scan_%s.html' % P['day'].iloc[0]), 'w', encoding='utf-8').write(html)
    if dry:
        print('[DRY]', subj)
    else:
        send(subj, html)
        print('已发：', subj)
    with open(os.path.join(LOG, 'send.log'), 'a', encoding='utf-8') as f:
        f.write('%s | %s | %d只 | %s\n' % (datetime.now(BJ).strftime('%Y-%m-%d %H:%M:%S'),
                                           subj, len(cand), 'DRY' if dry else 'OK'))


# ---------------- confirm：9:25 竞价确认 ----------------
def do_confirm(dry=False):
    p = os.path.join(LOG, 'cand_latest.json')
    if not os.path.exists(p):
        print('无候选池，先跑 scan')
        return
    C = json.load(open(p, encoding='utf-8'))
    cand = C.get('cand') or []
    print('候选池 %d 只（基准日 %s）' % (len(cand), C.get('day')))
    codes = [x['code'] for x in cand]
    q = quotes(codes)
    hit = []
    for x in cand:
        c = x['code']
        v = q.get(c)
        if not v or v['prev'] <= 0 or v['open'] <= 0:
            continue
        op = (v['open'] / v['prev'] - 1) * 100
        if LOW_LO <= op < LOW_HI:
            hit.append(dict(x, open=v['open'], open_pct=round(op, 2)))
    print('竞价低开命中 %d 只' % len(hit))
    body = ['<div style="font-family:Microsoft YaHei,sans-serif;max-width:720px">']
    now = datetime.now(BJ)
    if hit:
        body.append('<h2 style="font-size:17px;color:#c00">竞价确认 %d 只 · 现在可下单</h2>' % len(hit))
        body.append('<p style="font-size:13px">买法：<b>按当前价挂单</b>（9:30 前）；'
                    '卖出：涨停继续持有，不涨停当天收盘走；硬止损 8%。</p>')
        body.append('<table style="width:100%;border-collapse:collapse;font-size:13px">')
        body.append('<tr style="background:#f9fafb"><th align=left>代码</th><th align=left>名称</th>'
                    '<th align=right>竞价开盘</th><th align=right>低开</th><th align=right>昨收</th>'
                    '<th align=left>振幅/距高</th></tr>')
        for r in hit:
            body.append('<tr><td><b>%s</b></td><td>%s</td><td align=right>%.2f</td>'
                        '<td align=right style="color:#0a0"><b>%+.2f%%</b></td>'
                        '<td align=right>%.2f</td><td>%s / %s</td></tr>' % (
                            r['code'], r['name'], r['open'], r['open_pct'], r['close'],
                            ('%.1f%%' % r['amp']), ('%.1f%%' % r['dd250']) if r['dd250'] is not None else '-'))
        body.append('</table>')
        subj = '【竞价确认】%s 可买 %d 只 · 9:30 前下单' % (now.strftime('%m-%d'), len(hit))
    else:
        body.append('<h3>今日无符合条件（竞价没进 -7%%~-3%% 区间）</h3>')
        body.append('<p style="font-size:13px">不买。等下次。</p>')
        subj = '【竞价确认】%s 无符合条件，不买' % now.strftime('%m-%d')
    body.append('<p style="font-size:12px;color:#6b7280">区间依据：2016–2026 回测 3188 笔，'
                '该区间笔均 +1.05%%、胜率 52.5%%；高于 -3%% 溢价被吃，低于 -7%% 多为一字跌停买不到。</p>')
    html = ''.join(body)
    open(os.path.join(LOG, 'confirm_%s.html' % now.strftime('%Y%m%d')), 'w', encoding='utf-8').write(html)
    if dry:
        print('[DRY]', subj)
    else:
        send(subj, html)
        print('已发：', subj)
    with open(os.path.join(LOG, 'send.log'), 'a', encoding='utf-8') as f:
        f.write('%s | %s | %d只 | %s\n' % (now.strftime('%Y-%m-%d %H:%M:%S'), subj,
                                           len(hit), 'DRY' if dry else 'OK'))


if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else 'scan'
    dry = '--dry' in sys.argv
    # --wait：等到 09:25:35 再跑（应对 GitHub Actions 排队延迟）
    if '--wait' in sys.argv:
        now = datetime.now(BJ)
        target = now.replace(hour=9, minute=25, second=35, microsecond=0)
        if now < target:
            wait = (target - now).total_seconds()
            print('等待竞价撮合 %.0f 秒...' % wait, flush=True)
            time.sleep(wait)
    if mode == 'scan':
        do_scan(dry)
    else:
        do_confirm(dry)
