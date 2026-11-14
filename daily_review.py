# -*- coding: utf-8 -*-
"""每日复盘：用今日真实涨跌核对昨日推送，写回盘文件供次日校正"""
import os, sys, json, urllib.request, smtplib, ssl
from datetime import datetime, timezone, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
BJ = timezone(timedelta(hours=8))
LOG = os.path.join(BASE, '_push_logs')
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
SMTP_USER = os.environ.get('SMTP_USER', 'h1533165068@qq.com')
SMTP_PASS = os.environ.get('SMTP_PASS', 'xfboalpjikugjfgg')
MAIL_TO = os.environ.get('MAIL_TO', 'h1533165068@qq.com')


def q(codes):
    out = {}
    for i in range(0, len(codes), 60):
        ch = codes[i:i + 60]
        u = 'https://qt.gtimg.cn/q=' + ','.join(('sh' if c.startswith(('6', '5')) else 'sz') + c for c in ch)
        try:
            t = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=12)\
                .read().decode('gbk', 'ignore')
            for ln in t.split(';'):
                if '=' not in ln:
                    continue
                f = ln.split('=', 1)[1].strip('"').split('~')
                if len(f) < 40:
                    continue
                try:
                    out[f[2]] = dict(name=f[1], open=float(f[5] or 0), price=float(f[3] or 0),
                                     chg=float(f[32] or 0))
                except Exception:
                    pass
        except Exception:
            continue
    return out


def index_chg():
    u = 'https://qt.gtimg.cn/q=sh000001,sz399006,sh000852,sh000016'
    out = {}
    try:
        t = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=12)\
            .read().decode('gbk', 'ignore')
        for ln in t.split(';'):
            if '=' not in ln:
                continue
            f = ln.split('=', 1)[1].strip('"').split('~')
            if len(f) < 40:
                continue
            out[f[1]] = float(f[32])
    except Exception:
        pass
    return out


def main():
    lp = os.path.join(LOG, 'latest_v3.json')
    if not os.path.exists(lp):
        print('无清单，跳过复盘', flush=True)
        return
    d = json.load(open(lp, encoding='utf-8'))
    sigs = d.get('signals') or []
    base = d.get('base_day', '')
    if not sigs:
        print('昨日无信号，复盘：空仓', flush=True)
        return
    Q = q([s['code'] for s in sigs])
    idx = index_chg()
    rows = []
    for s in sigs:
        v = Q.get(s['code'])
        if not v or v['open'] <= 0:
            continue
        buy = v['open']                  # 口径：次日开盘价买入
        ret = (v['price'] / buy - 1) * 100
        rows.append(dict(code=s['code'], name=v['name'], buy=round(buy, 2),
                         close=round(v['price'], 2), ret=round(ret, 2)))
    if not rows:
        print('无行情，跳过', flush=True)
        return
    mean = sum(r['ret'] for r in rows) / len(rows)
    win = sum(1 for r in rows if r['ret'] > 0)
    cyb = idx.get('创业板指', 0.0)
    lines = ['# 每日复盘 %s' % datetime.now(BJ).strftime('%Y-%m-%d'),
             '',
             '清单基准日：%s ｜ 标的 %d 只 ｜ 口径：次日开盘买入、当日收盘' % (base, len(rows)),
             '',
             '- 组合等权收益：**%+.2f%%**' % mean,
             '- 正收益：%d/%d' % (win, len(rows)),
             '- 创业板指：%+.2f%% ｜ 超额：**%+.2f 个点**' % (cyb, mean - cyb),
             '- 上证 %+.2f%% ｜ 中证1000 %+.2f%% ｜ 上证50 %+.2f%%' % (
                 idx.get('上证指数', 0), idx.get('中证1000', 0), idx.get('上证50', 0)),
             '',
             '| 代码 | 名称 | 买入 | 收盘 | 收益 |', '|---|---|---|---|---|']
    for r in rows:
        lines.append('| %s | %s | %.2f | %.2f | %+.2f%% |' % (
            r['code'], r['name'], r['buy'], r['close'], r['ret']))
    lines += ['', '## 校正记录', '',
              '- 数据源：qt.gtimg.cn 实时快照；指数用带 sh/sz 前缀的指数代码',
              '- 本文件由 daily_review.py 自动生成，供次日推送前核对']
    txt = '\n'.join(lines)
    fp = os.path.join(LOG, 'review_%s.md' % datetime.now(BJ).strftime('%Y%m%d'))
    open(fp, 'w', encoding='utf-8').write(txt)
    print(txt, flush=True)
    print('已写 %s' % fp, flush=True)


if __name__ == '__main__':
    main()
