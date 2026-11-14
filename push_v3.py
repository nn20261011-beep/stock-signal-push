# -*- coding: utf-8 -*-
"""
push_v3.py —— 每日选股推送（战法池 v3，替换旧 13 套策略 / 低开一进二）

数据源：_hist.pkl.gz（全市场日线，live_fetch.py 每天增量更新）
战法源：strategies_by_state.json —— 101.0 万战法穷举后按市况分组选出的 66 条调度战法
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
VERSION = 'v3.3 / 战法池2026-11-12 / 101.0万战法穷举 / 66条调度战法(全量18781条筛出)'

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

    # ---- 合并题材/身位特征（22 条题材战法需要） ----
    try:
        import concept_feat
        cf = concept_feat.compute(K)
        for c, v in cf.items():
            if c in feats:
                feats[c].update(v)
        print('题材特征已合并 %d 只' % len(cf), flush=True)
    except Exception as e:
        print('题材特征计算失败（题材战法本轮不参与）：%s' % e, flush=True)
        cf = {}
        S = [s for s in S if 'c_' not in s['conds']]

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

    # ---- 判天：定今日市场状态 → 从调度表取该状态专属战法 ----
    cluster, top3, ms = None, None, None
    try:
        import market_state
        ms = market_state.compute(K)
        cluster, top3 = market_state.classify(ms)
        print('今日市场状态：类%s（最近3类距离 %s）' % (cluster, top3), flush=True)
        sp = os.path.join(BASE, 'strategies_by_state.json')
        if os.path.exists(sp):
            SCH = json.load(open(sp, encoding='utf-8'))
            got = SCH.get(str(cluster)) or []
            if got:
                S = got
                print('调度表命中：类%s → %d 条专属战法（该状态历史日等权 %s）' % (
                    cluster, len(S),
                    ' / '.join('%+.2f%%' % x['state_deq'] for x in S[:3])), flush=True)
            else:
                print('调度表里类%s 无可用战法（样本不足），今日空仓' % cluster, flush=True)
                S = []
        else:
            print('无调度表，用通用战法池兜底', flush=True)
    except Exception as e:
        print('判天失败，本轮全量战法兜底：%s' % e, flush=True)

    # 环境暴露：数据已证明「按环境择时」无预测力，因此不空仓，
    # 只在环境明显转弱时减少当日新开仓数量（降低暴露，不预测）
    max_picks = 8
    if ms is not None:
        try:
            if float(ms.get('earn') or 0) < -1.0 or float(ms.get('dt_n') or 0) >= 30:
                max_picks = 4
        except Exception:
            pass
    print('今日目标开仓上限 %d 只（单票 10%%）' % max_picks, flush=True)

    hits = []
    for si, s in enumerate(S):
        for c, f in feats.items():
            if match(f, s['conds']):
                hits.append(dict(sid=si, code=c, name=name_of.get(c, c), feat=f, s=s))

    # 去重：同一票保留年化最高的战法
    bycode = {}
    def _rank(s):
        return s.get('ann', s.get('state_deq', s.get('best_deq', 0)))
    for h in sorted(hits, key=lambda x: -_rank(x['s'])):
        bycode.setdefault(h['code'], h)
    # 按战法分散：每条战法最多 2 只，全局最多 10 只
    per_sid, ranked = {}, []
    for h in sorted(bycode.values(), key=lambda x: -_rank(x['s'])):
        sid = h['sid']
        if per_sid.get(sid, 0) >= 2:
            continue
        per_sid[sid] = per_sid.get(sid, 0) + 1
        ranked.append(h)
        if len(ranked) >= max_picks:
            break
    print('命中 %d 条 / 去重后 %d 只 / 来自 %d 套战法' % (
        len(hits), len(ranked), len(per_sid)), flush=True)

    # ---- 邮件 ----
    body = ['<div style="font-family:Microsoft YaHei,sans-serif;max-width:780px;margin:auto;color:#111">']
    body.append('<h2 style="font-size:18px">%s 收盘信号 · 次日开盘买入</h2>' % today)
    body.append('<p style="font-size:12px;color:#6b7280">策略版本：%s<br>生成时间：%s（北京时间）</p>' % (VERSION, tstr))
    if ms:
        body.append('<p style="font-size:13px;background:#eef2ff;padding:8px;border-radius:6px">'
                    '<b>今日判天：类%s</b> ｜ 涨停 %.0f 家 / 跌停 %.0f 家 / 最高 %d 板 / '
                    '晋级率 %s / 赚钱效应 %s<br><span style="font-size:12px;color:#6b7280">'
                    '只启用该状态下历史为正的战法，共 %d 条在跑</span></p>' % (
                        cluster, ms['zt_n'], ms['dt_n'], ms['max_bd'],
                        ('%.1f%%' % ms['promote']) if np.isfinite(ms['promote']) else '—',
                        ('%+.2f%%' % ms['earn']) if np.isfinite(ms['earn']) else '—',
                        len(S)))
    if ranked:
        sell_desc = {'sl5': '跌 5% 立即止损 / 最长持 10 日',
                     'sl8': '跌 8% 立即止损 / 最长持 10 日',
                     'rbreak': '断板次日走',
                     'r10': '持满 10 日收盘卖',
                     'r5': '持满 5 日收盘卖',
                     'r3': '持满 3 日收盘卖',
                     'tp8': '涨 8% 止盈 / 最长持 10 日',
                     'tp5': '涨 5% 止盈 / 最长持 10 日',
                     'ma5_n': '跌破 MA5 次日走',
                     'ma10_n': '跌破 MA10 次日走'}
        used = sorted({h['s']['sell'] for h in ranked})
        sell_txt = '；'.join('%s → %s' % (k, sell_desc.get(k, k)) for k in used)
        body.append('<p style="font-size:13px">共 <b>%d</b> 只。买入口径：<b>T 日收盘出信号 → 次日开盘价买入</b>；'
                    '已剔除 ST/退市/除权。<br><b>仓位：单票 10%%，最多同时 8 只</b>%s。</p>' % (
                        len(ranked),
                        '；当前环境偏弱，今日开仓上限下调至 4 只' if max_picks == 4 else ''))
        body.append('<p style="font-size:13px;background:#fff7ed;padding:8px;border-radius:6px">'
                    '<b>卖出按各自战法执行</b>：%s</p>' % sell_txt)
        body.append('<table style="width:100%;border-collapse:collapse;font-size:13px">')
        body.append('<tr style="background:#f9fafb"><th align=left>代码</th><th align=left>名称</th>'
                    '<th align=right>今收</th><th align=left>命中战法</th><th align=right>该状态日等权</th>'
                    '<th align=left>卖出</th></tr>')
        SELL_TXT = {'sl5': '跌5%止损/上限10日', 'sl8': '跌8%止损/上限10日',
                    'rbreak': '断板次日走', 'r10': '持满10日', 'r5': '持满5日',
                    'r3': '持满3日', 'tp8': '涨8%止盈', 'tp5': '涨5%止盈',
                    'ma5_n': '跌破MA5走', 'ma10_n': '跌破MA10走'}
        for h in ranked:
            s, f = h['s'], h['feat']
            v = s.get('state_deq', s.get('best_deq', 0))
            body.append('<tr><td><b>%s</b></td><td>%s</td><td align=right>%.2f</td>'
                        '<td style="font-size:11px">%s</td><td align=right>%+.2f%%</td>'
                        '<td style="font-size:12px">%s</td></tr>' % (
                            h['code'], h['name'], f['close'], str(s['conds'])[:52],
                            v, SELL_TXT.get(s['sell'], s['sell'])))
        body.append('</table>')
        body.append('<p style="font-size:12px;color:#6b7280;margin-top:12px">战法来自 2016–2026 全市场 '
                    '559 万样本、101.0 万个候选战法的穷举筛选；回测口径为单票 10% 仓位、'
                    '最多同时 8 只。三段验证全正。</p>')
        subj = '【选股信号 %s】%s %d只 · 次日开盘买' % ('v3', today, len(ranked))
    else:
        if not S and ms:
            body.append('<p style="font-size:14px;color:#c00"><b>今日空仓</b>：当前市场状态（类%s）下，'
                        '该状态调度表下无可用战法，不出手。</p>' % cluster)
        body.append('<p style="font-size:14px">今日无战法命中，<b>不买</b>。</p>')
        body.append('<p style="font-size:12px;color:#6b7280">战法要求「缩量 + 窄幅 + 站上均线 + 温和上涨」，没有符合条件就不出手。</p>')
        subj = '【选股信号 v3】%s 无信号 · 不买' % today
    body.append('</div>')
    html = ''.join(body)

    open(os.path.join(LOG, 'mail_%s_v3.html' % today), 'w', encoding='utf-8').write(html)
    json.dump(dict(version=VERSION, time=tstr, base_day=today,
                   hits=len(hits), signals=[dict(code=h['code'], name=h['name'],
                   state_deq=h['s'].get('state_deq', h['s'].get('best_deq', 0)),
                   sell=h['s']['sell'], cluster=cluster,
                   conds=h['s']['conds']) for h in ranked]),
              open(os.path.join(LOG, 'latest_v3.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)

    if dry:
        print('[DRY] %s' % subj, flush=True)
        for h in ranked:
            print('  %s %s 该状态日等权%+.2f%% 卖点%s' % (
                h['code'], h['name'], h['s'].get('state_deq', h['s'].get('best_deq', 0)),
                h['s']['sell']), flush=True)
    else:
        send(subj, html)
        print('已发：%s' % subj, flush=True)
    with open(os.path.join(LOG, 'send.log'), 'a', encoding='utf-8') as f:
        f.write('%s | %s | %d只 | %s\n' % (tstr, subj, len(ranked), 'DRY' if dry else 'OK'))


if __name__ == '__main__':
    main()
