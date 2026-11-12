# -*- coding: utf-8 -*-
"""
push_v3.py —— 每日选股推送（战法池 v3，替换旧 13 套策略 / 低开一进二）

数据源：_hist.pkl.gz（全市场日线，live_fetch.py 每天增量更新）
战法源：strategies_v3.json —— 昨晚 74.99 万战法穷举后，各市况都稳、回撤<15% 的 30 条
买点：T 日收盘出信号 → T+1 开盘价买入（严格 T+1，买入当天不可卖）
卖点：每条战法自带，当前 30 条全为「止损 5% + 持有上限 10 日」

时间闸门（硬）：
  · 只在工作日 15:00 之后 ~ 次日 9:15 之前发「次日开盘买」清单
  · 若运行时间落在 9:15~15:00（盘中/开盘后），直接退出不发，绝不发过期信号
  · 每封信写明策略版本与生成时间，防止「研究更新了但云端跑旧版」
"""
import os, sys, json, gzip, pickle, smtplib, ssl, re
import numpy as np
import pandas as pd
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
VERSION = 'v3.0 / 战法池2026-11-12 / 74.99万战法穷举 / 30条稳健战法'

ZT_LO, ZT_HI = 9.8, 10.6
FEAT_ORDER = ['chg', 'r5p', 'r20p', 'r60p', 'p60', 'dd250', 'gap5', 'gap10', 'gap20',
              'gap60', 'vol_r', 'vol_std', 'amp', 'up_shadow', 'is_zt', 'bd',
              'zt120', 'maxbd250']


def load_hist():
    p = os.path.join(BASE, '_hist.pkl.gz')
    if not os.path.exists(p):
        return None
    with gzip.open(p, 'rb') as f:
        return pickle.load(f)


def build_features(K):
    """每只票最新交易日的特征（T 日收盘可得）"""
    rows = {}
    for c, v in K.items():
        ds = sorted(v.keys())
        n = len(ds)
        if n < 70:
            continue
        O = np.array([v[d][0] for d in ds], float)
        C = np.array([v[d][1] for d in ds], float)
        H = np.array([v[d][2] for d in ds], float)
        L = np.array([v[d][3] for d in ds], float)
        V = np.array([v[d][4] for d in ds], float)
        CH = np.zeros(n)
        CH[1:] = (C[1:] / C[:-1] - 1) * 100
        i = n - 1
        pc = C[i - 1]
        if pc <= 0 or C[i] <= 0:
            continue
        zt = (CH >= ZT_LO) & (CH <= ZT_HI)
        bd = np.zeros(n, int)
        for k in range(n):
            bd[k] = (bd[k - 1] + 1) if (k > 0 and zt[k]) else (1 if zt[k] else 0)
        v20 = float(np.mean(V[i - 20:i])) if n > 20 else 1
        v5 = float(np.mean(V[i - 5:i])) if n > 5 else 1
        c60 = C[i - 59:i + 1] if n >= 60 else C[:i + 1]
        hi250 = float(np.max(H[max(0, i - 249):i + 1]))
        body = abs(C[i] - O[i])
        rows[c] = dict(
            code=c, day=ds[i], close=round(float(C[i]), 2),
            chg=float(CH[i]),
            r5p=(C[i] / C[i - 5] - 1) * 100 if n > 5 and C[i - 5] > 0 else 0,
            r20p=(C[i] / C[i - 20] - 1) * 100 if n > 20 and C[i - 20] > 0 else 0,
            r60p=(C[i] / C[i - 60] - 1) * 100 if n > 60 and C[i - 60] > 0 else 0,
            p60=float((c60 < C[i]).sum()) / len(c60) * 100,
            dd250=(C[i] / hi250 - 1) * 100 if hi250 > 0 else 0,
            gap5=(C[i] / np.mean(C[i - 5:i]) - 1) * 100 if n > 5 else 0,
            gap10=(C[i] / np.mean(C[i - 10:i]) - 1) * 100 if n > 10 else 0,
            gap20=(C[i] / np.mean(C[i - 20:i]) - 1) * 100 if n > 20 else 0,
            gap60=(C[i] / np.mean(C[i - 60:i]) - 1) * 100 if n > 60 else 0,
            vol_r=V[i] / v20 if v20 > 0 else 0,
            vol_std=float(np.std(CH[i - 19:i + 1])),
            amp=(H[i] - L[i]) / pc * 100,
            up_shadow=(H[i] - max(O[i], C[i])) / body if body > 0 else 3.0,
            is_zt=int(zt[i]), bd=int(bd[i]),
            zt120=int(zt[max(0, i - 119):i + 1].sum()),
            maxbd250=int(np.max(bd[max(0, i - 249):i + 1])),
        )
    return rows


def match(feat, conds):
    for c in conds.split(' & '):
        c = c.strip()
        m = re.match(r'(\w+) in \(([^,]+),\s*([^\]]+)\]', c)
        if not m:
            return False
        f, lo, hi = m.group(1), m.group(2).strip(), m.group(3).strip()
        v = feat.get(f)
        if v is None:
            return False
        if lo != '-inf' and not (v > float(lo)):
            return False
        if hi != '+inf' and not (v <= float(hi)):
            return False
    return True


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
    tstr = now.strftime('%Y-%m-%d %H:%M:%S')

    # ---- 硬闸门：盘中不发「次日开盘买」清单 ----
    hm = now.hour * 60 + now.minute
    if not force and (9 * 60 + 15) <= hm < (15 * 60):
        msg = '当前 %s 处于开盘后时段，跳过（不发过期信号）' % tstr
        print(msg, flush=True)
        with open(os.path.join(LOG, 'send.log'), 'a', encoding='utf-8') as f:
            f.write('%s | SKIP | 盘中/开盘后 |\n' % tstr)
        return

    K = load_hist()
    if not K:
        print('无历史数据', flush=True)
        return
    S = json.load(open(os.path.join(BASE, 'strategies_v3.json'), encoding='utf-8'))
    ind = json.load(open(os.path.join(BASE, '_industry_all.json'), encoding='utf-8'))
    name_of = {c: (v.get('name') or '') for c, v in ind.items()}

    feats = build_features(K)
    today = max(f['day'] for f in feats.values())

    # ---- 去重：3 个错峰触发点，同一天只发一封 ----
    # 依据 send.log 里当天带 v3 标记的 OK 记录，不依赖状态文件（状态文件可能是 dry-run 残留）
    if not dry and not force:
        sp = os.path.join(LOG, 'send.log')
        if os.path.exists(sp):
            stamp = now.strftime('%Y-%m-%d')
            for line in open(sp, encoding='utf-8'):
                if line.startswith(stamp) and 'v3' in line and line.strip().endswith('OK'):
                    print('今日已发过 v3 信号，跳过', flush=True)
                    return
    # 硬过滤
    feats = {c: f for c, f in feats.items()
             if not ('ST' in name_of.get(c, '') or '退' in name_of.get(c, '')
                     or str(name_of.get(c, '')).replace(' ', '').startswith(('XR', 'XD', 'DR')))}
    print('基准日 %s / 候选 %d 只 / 战法 %d 条' % (today, len(feats), len(S)), flush=True)

    hits = []
    for si, s in enumerate(S):
        for c, f in feats.items():
            if match(f, s['conds']):
                hits.append(dict(sid=si, code=c, name=name_of.get(c, c), feat=f, s=s))

    # 去重：同一票保留年化最高的战法
    bycode = {}
    for h in sorted(hits, key=lambda x: -x['s']['ann']):
        bycode.setdefault(h['code'], h)
    # 按战法分散：每条战法最多 2 只，全局最多 10 只
    per_sid, ranked = {}, []
    for h in sorted(bycode.values(), key=lambda x: -x['s']['ann']):
        sid = h['sid']
        if per_sid.get(sid, 0) >= 2:
            continue
        per_sid[sid] = per_sid.get(sid, 0) + 1
        ranked.append(h)
        if len(ranked) >= 10:
            break
    print('命中 %d 条 / 去重后 %d 只 / 来自 %d 套战法' % (
        len(hits), len(ranked), len(per_sid)), flush=True)

    # ---- 邮件 ----
    body = ['<div style="font-family:Microsoft YaHei,sans-serif;max-width:780px;margin:auto;color:#111">']
    body.append('<h2 style="font-size:18px">%s 收盘信号 · 次日开盘买入</h2>' % today)
    body.append('<p style="font-size:12px;color:#6b7280">策略版本：%s<br>生成时间：%s（北京时间）</p>' % (VERSION, tstr))
    if ranked:
        body.append('<p style="font-size:13px">共 <b>%d</b> 只。买入口径：<b>T 日收盘出信号 → 次日开盘价买入</b>；'
                    '已剔除 ST/退市/除权。<b>卖出：买入后跌 5%% 立即止损，最长持有 10 个交易日</b>。</p>' % len(ranked))
        body.append('<table style="width:100%;border-collapse:collapse;font-size:13px">')
        body.append('<tr style="background:#f9fafb"><th align=left>代码</th><th align=left>名称</th>'
                    '<th align=right>今收</th><th align=left>命中战法</th><th align=right>年化</th>'
                    '<th align=right>回撤</th><th align=right>月开仓</th><th align=left>卖出</th></tr>')
        for h in ranked:
            s, f = h['s'], h['feat']
            sell = '止损5% / 上限10日' if s['sell'] == 'sl5' else (
                   '断板次日走' if s['sell'] == 'rbreak' else '止损8% / 上限10日')
            body.append('<tr><td><b>%s</b></td><td>%s</td><td align=right>%.2f</td>'
                        '<td style="font-size:11px">%s</td><td align=right>+%.1f%%</td>'
                        '<td align=right>%.1f%%</td><td align=right>%.1f</td><td>%s</td></tr>' % (
                            h['code'], h['name'], f['close'], str(s['conds'])[:52],
                            s['ann'], s['mdd'], s['per_mon'], sell))
        body.append('</table>')
        body.append('<p style="font-size:12px;color:#6b7280;margin-top:12px">战法来自 2016–2026 全市场 '
                    '559 万样本、74.99 万个候选战法的穷举筛选；所列年化/回撤为单票 20% 仓位、'
                    '最多同时 3 只的组合回测结果。三段验证全正，9/9 个市场状态为正。</p>')
        subj = '【选股信号 %s】%s %d只 · 次日开盘买' % ('v3', today, len(ranked))
    else:
        body.append('<p style="font-size:14px">今日无战法命中，<b>不买</b>。</p>')
        body.append('<p style="font-size:12px;color:#6b7280">30 条稳健战法均未触发。'
                    '这些战法要求「缩量 + 窄幅 + 站上均线 + 温和上涨」，没有符合条件就不出手。</p>')
        subj = '【选股信号 v3】%s 无信号 · 不买' % today
    body.append('</div>')
    html = ''.join(body)

    open(os.path.join(LOG, 'mail_%s_v3.html' % today), 'w', encoding='utf-8').write(html)
    json.dump(dict(version=VERSION, time=tstr, base_day=today,
                   hits=len(hits), signals=[dict(code=h['code'], name=h['name'],
                   ann=h['s']['ann'], mdd=h['s']['mdd'], sell=h['s']['sell'],
                   conds=h['s']['conds']) for h in ranked]),
              open(os.path.join(LOG, 'latest_v3.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)

    if dry:
        print('[DRY] %s' % subj, flush=True)
        for h in ranked:
            print('  %s %s 年化+%.1f%% 回撤%.1f%%' % (h['code'], h['name'], h['s']['ann'], h['s']['mdd']), flush=True)
    else:
        send(subj, html)
        print('已发：%s' % subj, flush=True)
    with open(os.path.join(LOG, 'send.log'), 'a', encoding='utf-8') as f:
        f.write('%s | %s | %d只 | %s\n' % (tstr, subj, len(ranked), 'DRY' if dry else 'OK'))


if __name__ == '__main__':
    main()
