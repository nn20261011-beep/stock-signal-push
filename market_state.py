# -*- coding: utf-8 -*-
"""云端实时判天：算今日 12 维市场向量 → 匹配 10 类聚类中心

输出 cluster id + 各类画像，供 push_v3.py 决定「今天该用哪批战法」
"""
import os, json
import numpy as np

BASE = os.path.dirname(os.path.abspath(__file__))
ZT_LO, ZT_HI = 9.8, 10.6


def compute(K):
    """K: {code: {day: (open, close, high, low, vol)}}"""
    days = sorted({d for v in K.values() for d in v})
    if len(days) < 260:
        return None
    today = days[-1]
    prev = days[-2]
    pre2 = days[-3]

    # 今日涨幅
    chg, amt = {}, 0.0
    for c, v in K.items():
        if today in v and prev in v:
            pc = v[prev][1]
            if pc > 0:
                chg[c] = (v[today][1] / pc - 1) * 100
                amt += v[today][4] * v[today][1]
    if len(chg) < 500:
        return None

    # 连板（今日）
    def zt_set(day):
        s = {}
        for c, v in K.items():
            if day not in v:
                continue
            ds = sorted(v.keys())
            i = ds.index(day)
            if i < 1:
                continue
            pc = v[ds[i - 1]][1]
            if pc <= 0:
                continue
            x = (v[day][1] / pc - 1) * 100
            if ZT_LO <= x <= ZT_HI:
                run = 1
                j = i - 1
                while j >= 1:
                    p2 = v[ds[j - 1]][1]
                    if p2 > 0 and ZT_LO <= (v[ds[j]][1] / p2 - 1) * 100 <= ZT_HI:
                        run += 1
                        j -= 1
                    else:
                        break
                s[c] = run
        return s

    zt = zt_set(today)
    dt_n = sum(1 for x in chg.values() if x <= -9.8)
    max_bd = max(zt.values()) if zt else 0

    # 晋级率 / 赚钱效应（昨日首板今日涨停、昨日涨停今日表现）
    pz = zt_set(prev)
    firsts = [c for c, b in pz.items() if b == 1]
    promote = sum(1 for c in firsts if c in zt) / len(firsts) * 100 if len(firsts) >= 10 else np.nan
    earn = np.mean([chg[c] for c in pz if c in chg]) if len(pz) >= 10 else np.nan

    # 成交额分位（近 250 日）
    amts = []
    for d in days[-250:]:
        a = 0.0
        for c, v in K.items():
            if d in v:
                a += v[d][4] * v[d][1]
        amts.append(a)
    amt_pct = float((np.array(amts) < amt).mean() * 100) if amts else 50.0

    # 趋势20
    tr20 = np.nan
    if len(days) > 20:
        p20 = days[-21]
        vals = []
        for c, v in K.items():
            if today in v and p20 in v and v[p20][1] > 0:
                vals.append((v[today][1] / v[p20][1] - 1) * 100)
        tr20 = float(np.median(vals)) if vals else np.nan

    arr = np.array(list(chg.values()), float)
    up_ratio = float((arr > 0).mean() * 100)
    med_chg = float(np.median(arr))
    vola = float(np.std(arr))

    tiers = {}
    for b in zt.values():
        tiers[b] = tiers.get(b, 0) + 1
    gap = 0
    if max_bd >= 3:
        for b in range(2, max_bd):
            if tiers.get(b, 0) == 0:
                gap += 1

    vec = [len(zt), dt_n, max_bd,
           promote if np.isfinite(promote) else 0.0,
           earn if np.isfinite(earn) else 0.0,
           amt_pct, tr20 if np.isfinite(tr20) else 0.0,
           up_ratio, med_chg, vola, gap,
           len(zt) / max(dt_n, 1)]
    return dict(day=today, vector=[float(x) for x in vec], zt_n=len(zt), dt_n=dt_n,
                max_bd=max_bd, promote=promote, earn=earn)


def classify(ms, centers_path=None):
    """标准化后取最近中心（欧氏距离）"""
    if not ms:
        return None, None
    p = centers_path or os.path.join(BASE, 'market_centers.json')
    C = json.load(open(p, encoding='utf-8'))
    mu = np.array(C['global_mean'], float)
    sd = np.array(C['global_std'], float)
    sd[sd == 0] = 1
    x = (np.array(ms['vector'], float) - mu) / sd
    dist = {}
    for k, v in C['classes'].items():
        ct = np.array(v['center'], float)
        dist[int(k)] = float(np.linalg.norm(x - ct))
    best = min(dist, key=dist.get)
    return best, dict(sorted(dist.items(), key=lambda z: z[1])[:3])


if __name__ == '__main__':
    import gzip, pickle
    with gzip.open(os.path.join(BASE, '_hist.pkl.gz'), 'rb') as f:
        K = pickle.load(f)
    ms = compute(K)
    if not ms:
        print('数据不足')
    else:
        c, top = classify(ms)
        print('基准日 %s' % ms['day'])
        print('  涨停%.0f 跌停%.0f 最高%d板 晋级%.1f%% 赚钱%+.2f%%' % (
            ms['zt_n'], ms['dt_n'], ms['max_bd'],
            ms['promote'] if np.isfinite(ms['promote']) else -99,
            ms['earn'] if np.isfinite(ms['earn']) else -99))
        print('  → 市场状态 类%d（最近3类距离：%s）' % (c, top))
        C = json.load(open(os.path.join(BASE, 'market_centers.json'), encoding='utf-8'))
        print('  该类历史画像：n=%d 涨停%.0f 跌停%.0f 最高板%.1f 晋级%.1f%%' % (
            C['classes'][str(c)]['n'], *C['classes'][str(c)]['raw_mean'][:4]))
