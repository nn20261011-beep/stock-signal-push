# -*- coding: utf-8 -*-
"""
fill_trades.py —— 成交回填：把历史推送标的的真实盈亏写回 discipline 状态

数据源：_push_logs/*.html（历史推送）、_push_logs/decision_*.json（v4 决策）、_kline_raw（全历史日线）
口径：T 日推送 → T+1 开盘价买入 → T+1 收盘价卖出（保守口径，扣 0.1% 费用）
     带 --sell-mode=hold 时按各票类卖点从日线现算（断板次日走 / 止损5% / 持满10日）
"""
import os, sys, re, glob, json, pickle
from datetime import datetime, timezone, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
LOG = os.path.join(BASE, '_push_logs')
sys.path.insert(0, BASE)
import discipline

BJ = timezone(timedelta(hours=8))


def load_kline():
    K = {}
    for fp in glob.glob(os.path.join(ROOT, '_kline_raw', '*.pkl')):
        c = os.path.basename(fp).replace('.pkl', '')
        try:
            K[c] = pickle.load(open(fp, 'rb'))
        except Exception:
            pass
    return K


def parse_pushes():
    """返回 [(base_day, codes, source)]"""
    out = []
    for f in sorted(glob.glob(os.path.join(LOG, '*.html'))):
        t = open(f, encoding='utf-8').read()
        codes = re.findall(r'<td><b>(\d{6})</b></td>', t)
        if not codes:
            continue
        m = re.search(r'(\d{4}-\d{2}-\d{2})', os.path.basename(f))
        if not m:
            m2 = re.search(r'(\d{4})(\d{2})(\d{2})', os.path.basename(f))
            day = '%s-%s-%s' % m2.groups() if m2 else None
        else:
            day = m.group(1)
        if not day:
            m = re.search(r'(\d{4}-\d{2}-\d{2})', t)
            day = m.group(1) if m else None
        if not day:
            continue
        out.append((day, sorted(set(codes)), os.path.basename(f)))
    for f in sorted(glob.glob(os.path.join(LOG, 'decision_*.json'))):
        try:
            d = json.load(open(f, encoding='utf-8'))
        except Exception:
            continue
        picks = d.get('picks') or []
        passed = [p['code'] for p in picks if p.get('doctrine_ok', True)]
        if passed and d.get('day'):
            out.append((d['day'], sorted(set(passed)), os.path.basename(f)))
    # 兜底：latest_v3.json
    lp = os.path.join(LOG, 'latest_v3.json')
    if os.path.exists(lp):
        try:
            d = json.load(open(lp, encoding='utf-8'))
            out.append((d['base_day'], sorted(set(s['code'] for s in d.get('signals', []))),
                        'latest_v3.json'))
        except Exception:
            pass
    return out


def calc_trade(K, code, base_day, sell_mode='simple'):
    rec = K.get(code)
    if not rec:
        return None
    ds = sorted(rec)
    # 找 base_day 当日或之后第一个交易日
    idx = None
    for i, d in enumerate(ds):
        if d >= base_day:
            idx = i
            break
    if idx is None or idx + 2 >= len(ds):
        return None          # 尚未到可卖出日 → 持仓中，不回填已实现盈亏
    bd = ds[idx]
    nd = ds[idx + 1]
    buy = rec[nd][0]                  # 次日开盘
    if buy <= 0:
        return None
    if sell_mode == 'simple':
        # T+1 买、最早 T+2 卖；没有 T+2 数据则视为持仓中
        if idx + 2 >= len(ds):
            return None
        sell = rec[ds[idx + 2]][1]
        hold = 2
    else:
        sell, hold = None, 2
        for k in range(idx + 2, min(idx + 11, len(ds))):
            d = ds[k]
            low = rec[d][3]
            close = rec[d][1]
            prev = rec[ds[k - 1]][1] if k > 0 else close
            chg = (close / prev - 1) * 100 if prev > 0 else 0
            if low <= buy * 0.95:     # 触及止损
                sell, hold = buy * 0.95, k - idx
                break
            if not (9.8 <= chg <= 10.6) and k > idx + 1:   # 断板次日走
                sell, hold = close, k - idx
                break
        if sell is None:
            kk = min(idx + 10, len(ds) - 1)
            sell, hold = rec[ds[kk]][1], kk - idx
    pnl = (sell / buy - 1) * 100 - 0.1
    return dict(code=code, base_day=bd, buy_day=nd, buy=round(buy, 2),
                sell=round(sell, 2), pnl=round(pnl, 2), hold=hold)


def main():
    sell_mode = 'hold' if '--sell-mode=hold' in sys.argv else 'simple'
    reset = '--reset' in sys.argv
    if reset:
        discipline.save(dict(discipline.DEFAULT))
    K = load_kline()
    pushes = parse_pushes()
    print('历史推送 %d 批 / 日线 %d 只 / 口径 %s' % (len(pushes), len(K), sell_mode), flush=True)
    done = []
    open_pos = []
    import re as _re
    _st = discipline.load()
    _seen = set()
    for t in _st.get('trades', []):
        m = _re.search(r'(\d{4}-\d{2}-\d{2})\s*买', t.get('note', ''))
        if m:
            _seen.add((m.group(1), t.get('code')))
    for day, codes, src in pushes:
        for c in codes:
            t = calc_trade(K, c, day, sell_mode)
            if not t:
                if c in K:
                    ds = sorted(K[c])
                    nxt = [d for d in ds if d > day]
                    if nxt:
                        open_pos.append(dict(code=c, day=day, buy_day=nxt[0],
                                             buy=round(K[c][nxt[0]][0], 2), src=src))
                continue
            key = (t['buy_day'], c)
            if key in [x['key'] for x in done] or key in _seen:
                continue
            done.append(dict(key=key, **t))
            discipline.record_trade(t['pnl'], c,
                                    '%s 推送 → %s 买 %.2f → 卖 %.2f（持%d日）' % (
                                        day, t['buy_day'], t['buy'], t['sell'], t['hold']))
    st = discipline.load()
    print('')
    print('回填 %d 笔 / 持仓中 %d 只 / trades=%d / equity=%.4f / loss_streak=%d' % (
        len(done), len(open_pos), len(st['trades']), st['equity'], st['loss_streak']))
    json.dump(open_pos, open(os.path.join(LOG, 'open_positions.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    for x in done[:8]:
        print('  %s %s 买%.2f 卖%.2f %+.2f%% 持%d日' % (
            x['buy_day'], x['code'], x['buy'], x['sell'], x['pnl'], x['hold']))
    # 模式健康度同步刷新
    import review_mode
    h = review_mode.evaluate()
    print('')
    print('模式健康：factor=%.1f n=%d verdict=%s' % (h['factor'], h['n'], h['verdict']))
    # 允许开仓检查
    allow, blocks, factor = discipline.check_before_open()
    print('纪律检查：allow=%s blocks=%s factor=%.1f' % (allow, blocks, factor))


if __name__ == '__main__':
    main()
