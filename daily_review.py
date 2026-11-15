# -*- coding: utf-8 -*-
"""每日复盘：统一读 decision_*.json → 算真实盈亏 → 写回 discipline → 刷新模式健康"""
import os, sys, json, glob, urllib.request
from datetime import datetime, timezone, timedelta
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
LOG = os.path.join(BASE, '_push_logs')
BJ = timezone(timedelta(hours=8))
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}


def q(codes):
    out = {}
    for i in range(0, len(codes), 60):
        ch = codes[i:i + 60]
        u = 'https://qt.gtimg.cn/q=' + ','.join(('sh' if c.startswith(('6', '5')) else 'sz') + c for c in ch)
        try:
            t = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=12).read().decode('gbk', 'ignore')
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
    out = {}
    try:
        t = urllib.request.urlopen(urllib.request.Request(
            'https://qt.gtimg.cn/q=sh000001,sz399006,sh000852,sh000016', headers=UA),
            timeout=12).read().decode('gbk', 'ignore')
        for ln in t.split(';'):
            if '=' not in ln:
                continue
            f = ln.split('=', 1)[1].strip('"').split('~')
            if len(f) >= 40:
                out[f[1]] = float(f[32])
    except Exception:
        pass
    return out


def main():
    dec = sorted(glob.glob(os.path.join(LOG, 'decision_*.json')))
    lp = dec[-1] if dec else os.path.join(LOG, 'latest_v3.json')
    if not os.path.exists(lp):
        print('无决策文件，跳过复盘', flush=True)
        return
    d = json.load(open(lp, encoding='utf-8'))
    picks = d.get('picks') or d.get('signals') or []
    base = d.get('day') or d.get('base_day') or ''
    Q = q([x['code'] for x in picks]) if picks else {}
    idx = index_chg()
    rows = []
    for x in picks:
        c = x['code']
        v = Q.get(c)
        if not v or v['open'] <= 0:
            continue
        buy = x.get('buy_price') or v['open']
        ret = (v['price'] / buy - 1) * 100 - 0.1
        rows.append(dict(code=c, name=v['name'], buy=round(buy, 2),
                         close=round(v['price'], 2), ret=round(ret, 2),
                         type=x.get('type', ''), sell=x.get('sell', '')))
    lines = ['# 每日复盘 %s' % datetime.now(BJ).strftime('%Y-%m-%d'), '',
             '决策基准日：%s ｜ 标的 %d 只 ｜ 数据源 %s' % (base, len(rows), os.path.basename(lp)), '']
    if rows:
        mean = sum(r['ret'] for r in rows) / len(rows)
        win = sum(1 for r in rows if r['ret'] > 0)
        cyb = idx.get('创业板指', 0.0)
        lines += ['- 组合等权收益：**%+.2f%%**' % mean,
                  '- 正收益：%d/%d' % (win, len(rows)),
                  '- 创业板指 %+.2f%% ｜ 超额 **%+.2f 个点**' % (cyb, mean - cyb),
                  '- 上证 %+.2f%% ｜ 中证1000 %+.2f%% ｜ 上证50 %+.2f%%' % (
                      idx.get('上证指数', 0), idx.get('中证1000', 0), idx.get('上证50', 0)), '',
                  '| 代码 | 名称 | 买入 | 收盘 | 收益 | 类型 | 卖点 |', '|---|---|---|---|---|---|---|']
        for r in rows:
            lines.append('| %s | %s | %.2f | %.2f | %+.2f%% | %s | %s |' % (
                r['code'], r['name'], r['buy'], r['close'], r['ret'], r['type'], r['sell']))
        # 写回纪律状态（按 buy_day+code 去重）
        import discipline, review_mode
        st = discipline.load()
        seen = set((t.get('day'), t.get('code')) for t in st.get('trades', []))
        today = datetime.now(BJ).strftime('%Y-%m-%d')
        added = 0
        for r in rows:
            if (today, r['code']) in seen:
                continue
            discipline.record_trade(r['ret'], r['code'], '复盘 %s 收盘' % base)
            added += 1
        discipline.set_daily_pnl(mean)
        h = review_mode.evaluate()
        lines += ['', '## 状态回写', '',
                  '- 新增成交 %d 笔 / trades 总数 %d' % (added, len(discipline.load()['trades'])),
                  '- 单日盈亏 %+.2f%% 已写入 discipline' % mean,
                  '- 模式健康：factor=%.1f（%s）' % (h['factor'], h['verdict'])]
    else:
        lines += ['- 今日无可核对标的（空仓或行情缺失）']
    lines += ['', '口径：qt.gtimg.cn 实时快照；指数用带 sh/sz 前缀的指数代码。']
    txt = '\n'.join(lines)
    fp = os.path.join(LOG, 'review_%s.md' % datetime.now(BJ).strftime('%Y%m%d'))
    open(fp, 'w', encoding='utf-8').write(txt)
    print(txt, flush=True)
    print('已写 %s' % fp, flush=True)


if __name__ == '__main__':
    main()
