# -*- coding: utf-8 -*-
"""
市场状态判定模块（严格复刻 market_state3.py，无未来函数）
状态库：docs/state_history.csv（day, zt_n, dt_n, max_bd, bd2_n, bd3_n, zbp_rate, earn, med_chg, n）
前一交易日涨停名单：docs/zt_prev.csv（code）

regime(D) 的算法（来自 market_state3.py）：
    bd   = max_bd(D-1)
    earn = earn(D-1) = 涨停名单(D-2) 的股票在 D-1 的平均涨幅
    if earn < -1.5          → 冰点期
    elif bd >= 6 and earn >= 1.0 → 高潮期
    elif bd >= 4 and earn > 0    → 发酵期
    elif bd <= 3            → 低迷期
    else                    → 分化期
"""
import os
import csv
import json

STATE_CSV = os.path.join('docs', 'state_history.csv')
ZT_PREV = os.path.join('docs', 'zt_prev.csv')


def load_state():
    """返回 [(dict), ...]，按 day 升序"""
    if not os.path.exists(STATE_CSV):
        return []
    rows = []
    with open(STATE_CSV, 'r', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            rows.append(r)
    rows.sort(key=lambda x: x['day'])
    return rows


def calc_regime(prev_row):
    """用前一日的 max_bd 和 earn 算今日 regime"""
    try:
        bd = float(prev_row['max_bd'])
        earn = float(prev_row['earn'])
    except Exception:
        return 'NA'
    if earn != earn:      # NaN
        return 'NA'
    if earn < -1.5:
        return '冰点期'
    if bd >= 6 and earn >= 1.0:
        return '高潮期'
    if bd >= 4 and earn > 0:
        return '发酵期'
    if bd <= 3:
        return '低迷期'
    return '分化期'


def load_zt_prev():
    if not os.path.exists(ZT_PREV):
        return []
    with open(ZT_PREV, 'r', encoding='utf-8') as f:
        return [r['code'] for r in csv.DictReader(f) if r.get('code')]


def save_zt_prev(codes):
    os.makedirs('docs', exist_ok=True)
    with open(ZT_PREV, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['code'])
        for c in codes:
            w.writerow([c])


def compute_today_metrics(quotes, zt_prev_codes, zt_bd_map):
    """用今日快照 + 前日涨停名单，算今日的指标（用于追加历史库）"""
    zt = [q for q in quotes.values() if q['pct'] >= 9.8]
    dt = [q for q in quotes.values() if q['pct'] <= -9.8]
    zbc = 0
    for q in quotes.values():
        if q['prev'] > 0 and q['pct'] < 9.8:
            if (q['high'] / q['prev'] - 1) * 100 >= 9.8:
                zbc += 1
    touch = len(zt) + zbc
    zbp = round(zbc / touch * 100, 1) if touch else 0.0

    # earn = 前一日涨停股今日平均涨幅
    vals = []
    for c in zt_prev_codes:
        q = quotes.get(c)
        if q:
            vals.append(q['pct'])
    earn = round(sum(vals) / len(vals), 2) if vals else float('nan')

    max_bd = max([zt_bd_map.get(q['code'], 1) for q in zt], default=0)
    bd2 = sum(1 for q in zt if zt_bd_map.get(q['code'], 1) >= 2)
    bd3 = sum(1 for q in zt if zt_bd_map.get(q['code'], 1) >= 3)
    med = 0.0
    if quotes:
        pcts = sorted(q['pct'] for q in quotes.values())
        med = round(pcts[len(pcts) // 2], 2)

    return {
        'zt_n': len(zt), 'dt_n': len(dt), 'max_bd': max_bd,
        'bd2_n': bd2, 'bd3_n': bd3, 'zbp_rate': zbp,
        'earn': earn, 'med_chg': med, 'n': len(quotes),
        'zt_codes': [q['code'] for q in zt],
    }


def append_state(day, m):
    """把今日指标追加进历史库（同一天覆盖）"""
    rows = load_state()
    rows = [r for r in rows if r['day'] != day]
    rows.append({
        'day': day, 'zt_n': m['zt_n'], 'dt_n': m['dt_n'], 'max_bd': m['max_bd'],
        'bd2_n': m['bd2_n'], 'bd3_n': m['bd3_n'], 'zbp_rate': m['zbp_rate'],
        'earn': m['earn'], 'med_chg': m['med_chg'], 'n': m['n'],
    })
    rows.sort(key=lambda x: x['day'])
    os.makedirs('docs', exist_ok=True)
    with open(STATE_CSV, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['day', 'zt_n', 'dt_n', 'max_bd', 'bd2_n',
                                          'bd3_n', 'zbp_rate', 'earn', 'med_chg', 'n'])
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return len(rows)
