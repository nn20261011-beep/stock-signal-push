# -*- coding: utf-8 -*-
"""
intraday_guard.py —— 盘中执行修正（不是推翻早盘信号）

原则（用户 11-13 23:09 定）：
  · 早盘 9:25 的信号是「作战计划」，只对 T-1 收盘信息负责
  · 盘中只判断「计划是否还成立」，不改标的池、不新增票
  · 每天最多 1 封修正邮件
  · 措辞固定「原计划 X → 触发 Y → 执行 Z」，不写「更正/之前错了」

触发条件（全部是已发生的事实，不是预测）：
  T1 止损：现价 ≤ 买入价×0.95
  T2 高开低走：现价 < 当日均价 且 现价 ≤ 买入价×0.97
  T3 大盘突变：创业板指当日 ≤ −2.5% 且 开盘时 > −1%
  T4 止盈：现价 ≥ 买入价×1.08
"""
import os, sys, json, smtplib, ssl, urllib.request
from datetime import datetime, timezone, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
BJ = timezone(timedelta(hours=8))
LOG = os.path.join(BASE, '_push_logs')
os.makedirs(LOG, exist_ok=True)
SMTP_USER = os.environ.get('SMTP_USER', 'h1533165068@qq.com')
SMTP_PASS = os.environ.get('SMTP_PASS', 'xfboalpjikugjfgg')
MAIL_TO = os.environ.get('MAIL_TO', 'h1533165068@qq.com')
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}


def quotes(codes):
    out = {}
    for i in range(0, len(codes), 60):
        ch = codes[i:i + 60]
        q = ','.join(('sh' if c.startswith(('6', '5')) else 'sz') + c for c in ch)
        u = 'https://qt.gtimg.cn/q=' + q
        try:
            txt = urllib.request.urlopen(urllib.request.Request(u, headers=UA),
                                         timeout=12).read().decode('gbk', 'ignore')
            for ln in txt.split(';'):
                if '=' not in ln:
                    continue
                f = ln.split('=', 1)[1].strip('"').split('~')
                if len(f) < 40 or not f[2]:
                    continue
                try:
                    vol = float(f[6] or 0)
                    amt = float(f[37] or 0)
                    out[f[2]] = dict(name=f[1], price=float(f[3] or 0),
                                     prev=float(f[4] or 0), open=float(f[5] or 0),
                                     chg=float(f[32] or 0),
                                     avg=(amt * 100.0 / vol) if vol > 0 else 0)
                except Exception:
                    pass
        except Exception:
            continue
    return out


def index_quotes():
    u = 'https://qt.gtimg.cn/q=sz399006'
    try:
        t = urllib.request.urlopen(urllib.request.Request(u, headers=UA),
                                   timeout=10).read().decode('gbk', 'ignore')
        f = t.split('=', 1)[1].strip('"').split('~')
        return dict(name=f[1], chg=float(f[32]), open=float(f[5]), prev=float(f[4]), price=float(f[3]))
    except Exception:
        return None


def send(subject, html):
    from email.mime.text import MIMEText
    from email.header import Header
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
    force = '--force' in sys.argv
    now = datetime.now(BJ)
    hm = now.hour * 100 + now.minute
    if not force and not (930 <= hm <= 1450):
        print('%s 不在盘中(9:30~14:50)，跳过' % now.strftime('%H:%M'), flush=True)
        return

    lp = os.path.join(LOG, 'latest_v3.json')
    if not os.path.exists(lp):
        print('无早盘清单，跳过', flush=True)
        return
    prev = json.load(open(lp, encoding='utf-8'))
    # 过期清单不修正：base_day 必须是最近 3 个交易日内
    try:
        import gzip, pickle
        with gzip.open(os.path.join(BASE, '_hist.pkl.gz'), 'rb') as f:
            K = pickle.load(f)
        latest = max(max(v) for v in K.values())
        bd = prev.get('base_day', '')
        if bd and bd < str(latest)[:10]:
            # 允许 T-1（清单是昨晚生成、今天执行）
            from datetime import date
            gap = (date.fromisoformat(str(latest)[:10]) - date.fromisoformat(bd)).days
            if gap > 4:
                print('清单过期（base_day=%s，行情最新=%s），跳过' % (bd, str(latest)[:10]), flush=True)
                return
    except Exception:
        pass
    sigs = prev.get('signals') or []
    if not sigs:
        print('早盘无信号，无需修正', flush=True)
        return
    # 买入价：用清单里的 close（T-1 收盘）作参考；实盘按开盘价买，这里用快照现价反推
    codes = [s['code'] for s in sigs]
    Q = quotes(codes)
    idx = index_quotes()

    # 大盘突变：用开盘涨幅作早盘状态
    market_alarm = False
    if idx:
        open_chg = (idx['open'] / idx['prev'] - 1) * 100 if idx['prev'] > 0 else 0
        market_alarm = (idx['chg'] <= -2.5) and (open_chg > -1.0)

    trig = []
    for s in sigs:
        c = s['code']
        v = Q.get(c)
        if not v or v['price'] <= 0:
            continue
        buy = s.get('close') or s.get('buy_price') or 0
        if not buy:
            # 用今开作买入价近似
            buy = v['open']
        if buy <= 0:
            continue
        p = v['price']
        ratio = p / buy - 1
        if ratio <= -0.05:
            trig.append(dict(code=c, name=v['name'], buy=round(buy, 2), now=p,
                             chg=round(ratio * 100, 2), tag='T1 止损',
                             act='已买入立即止损；未买入放弃'))
        elif ratio <= -0.03 and v['avg'] > 0 and p < v['avg']:
            trig.append(dict(code=c, name=v['name'], buy=round(buy, 2), now=p,
                             chg=round(ratio * 100, 2), tag='T2 高开低走',
                             act='放弃买入；已买入按跌破均价处理'))
        elif ratio >= 0.08:
            trig.append(dict(code=c, name=v['name'], buy=round(buy, 2), now=p,
                             chg=round(ratio * 100, 2), tag='T4 止盈',
                             act='按战法止盈规则减仓'))
    print('个股触发 %d 项 / 大盘突变 %s' % (len(trig), market_alarm), flush=True)

    if not trig and not market_alarm:
        print('无触发，不发修正（小幅波动不打扰）', flush=True)
        return

    st = os.path.join(LOG, 'guard_count_%s.txt' % now.strftime('%Y%m%d'))
    if not dry and not force:
        if os.path.exists(st) and int(open(st).read().strip() or 0) >= 1:
            print('今日已发过 1 封修正，跳过', flush=True)
            return

    body = ['<div style="font-family:Microsoft YaHei,sans-serif;max-width:740px;color:#111">']
    body.append('<h2 style="font-size:17px">盘中执行修正 · %s</h2>' % now.strftime('%m-%d %H:%M'))
    body.append('<p style="font-size:12px;color:#6b7280">原计划（%s 清单）继续执行；'
                '以下为触发条件后的动作调整，<b>不新增标的、不推翻原计划</b>。</p>' % prev.get('base_day', ''))
    if market_alarm and idx:
        body.append('<p style="background:#fff7ed;padding:8px;font-size:13px">'
                    '<b>原计划正常买入 → 触发：创业板指 %+0.2f%%（开盘 %+0.2f%%）→ 执行：'
                    '今日不再新开仓，已持仓按原止损</b></p>' % (idx['chg'], open_chg))
    if trig:
        body.append('<table style="width:100%;border-collapse:collapse;font-size:13px">')
        body.append('<tr style="background:#f9fafb"><th align=left>代码</th><th align=left>名称</th>'
                    '<th align=right>计划买入</th><th align=right>现价</th><th align=right>幅度</th>'
                    '<th align=left>触发</th><th align=left>执行</th></tr>')
        for t in trig:
            body.append('<tr><td><b>%s</b></td><td>%s</td><td align=right>%.2f</td>'
                        '<td align=right>%.2f</td><td align=right style="color:#093">%+.2f%%</td>'
                        '<td>%s</td><td>%s</td></tr>' % (
                            t['code'], t['name'], t['buy'], t['now'], t['chg'], t['tag'], t['act']))
        body.append('</table>')
    body.append('<p style="font-size:12px;color:#6b7280;margin-top:12px">'
                '触发条件为已发生的价格事实，不是预测。每日最多 1 封修正。</p></div>')
    html = ''.join(body)
    subj = '【盘中修正】%s %d项触发 · 原计划继续执行' % (now.strftime('%m-%d %H:%M'), len(trig))

    if dry:
        print('[DRY]', subj, flush=True)
        for t in trig:
            print('  %s %s 计划%.2f 现%.2f %+.2f%% → %s / %s' % (
                t['code'], t['name'], t['buy'], t['now'], t['chg'], t['tag'], t['act']), flush=True)
    else:
        send(subj, html)
        print('已发：%s' % subj, flush=True)
        n = int(open(st).read()) if os.path.exists(st) else 0
        open(st, 'w').write(str(n + 1))
    with open(os.path.join(LOG, 'send.log'), 'a', encoding='utf-8') as f:
        f.write('%s | %s | %d项 | %s\n' % (now.strftime('%Y-%m-%d %H:%M:%S'), subj,
                                           len(trig), 'DRY' if dry else 'OK'))


if __name__ == '__main__':
    main()
