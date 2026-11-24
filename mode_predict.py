# -*- coding: utf-8 -*-
"""
mode_predict.py —— 实盘判模式：用 mode_params.json 的 scaler+centers 预测今日模式
特征口径与 mode_cluster.py 完全一致（12 维，zt_n/dt_n 取 log1p）
指数抓取失败时用 0 并在返回值标注 index_ok=False
"""
import os, json, gzip, pickle
import numpy as np

BASE = os.path.dirname(os.path.abspath(__file__))

MODE_DESC = {
    'M1': '普跌·亏钱效应',
    'M2': '高标·连板断层',
    'M3': '普涨·健康',
}


def load_hist(path=None):
    p = path or os.path.join(BASE, '_hist.pkl.gz')
    with gzip.open(p, 'rb') as f:
        return pickle.load(f)


def fetch_index_chg():
    """拉上证/创业板当日涨跌（腾讯），失败返回 (0,0,False)"""
    import urllib.request
    try:
        u = 'https://qt.gtimg.cn/q=sh000001,sz399006'
        s = urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'}),
                                   timeout=15).read().decode('gbk', 'ignore')
        out = {}
        for line in s.split(';'):
            if '~' not in line:
                continue
            f = line.split('=', 1)[1].strip('"\n').split('~')
            out[f[2]] = float(f[32]) if len(f) > 32 else 0.0
        return out.get('000001', 0.0), out.get('399006', 0.0), True
    except Exception:
        return 0.0, 0.0, False


def compute_raw(K, prev_days=250):
    """从个股历史算 12 维原始特征（未标准化）"""
    days = sorted({d for v in K.values() for d in v})
    if len(days) < 30:
        return None
    today, prev = days[-1], days[-2]
    chg = {}
    amt = 0.0
    up = 0
    n = 0
    for c, rec in K.items():
        if today in rec and prev in rec and rec[prev][1] > 0:
            v = (rec[today][1] / rec[prev][1] - 1) * 100
            chg[c] = v
            n += 1
            if v > 0:
                up += 1
            amt += rec[today][4] * rec[today][1]
    if not chg:
        return None
    zt_n = sum(1 for v in chg.values() if 9.8 <= v <= 10.6)
    dt_n = sum(1 for v in chg.values() if v <= -9.8)
    bd = {}
    for c, rec in K.items():
        ds = sorted(rec)
        if ds[-1] != today:
            continue
        run = 0
        for j in range(len(ds)-1, max(len(ds)-13, -1), -1):
            if j == 0:
                break
            p0 = rec[ds[j-1]][1]
            if p0 > 0 and 9.8 <= (rec[ds[j]][1]/p0-1)*100 <= 10.6:
                run += 1
            else:
                break
        if run:
            bd[c] = run
    max_bd = max(bd.values()) if bd else 0
    tiers = {}
    for v in bd.values():
        tiers[v] = tiers.get(v, 0) + 1
    gap = 0
    for b in range(2, max_bd):
        if tiers.get(b, 0) == 0:
            gap += 1
    prev_zt = []
    for c, rec in K.items():
        ds = sorted(rec)
        if len(ds) < 3:
            continue
        p2 = rec[ds[-3]][1]
        if p2 > 0 and 9.8 <= (rec[ds[-2]][1]/p2-1)*100 <= 10.6:
            prev_zt.append(c)
    promote = 0.0
    if prev_zt:
        keep = sum(1 for c in prev_zt if chg.get(c, 0) >= 9.8)
        promote = keep / len(prev_zt) * 100
    earn = float(np.mean([chg[c] for c in prev_zt if c in chg])) if prev_zt else 0.0
    amts = []
    for d in days[-prev_days:]:
        s = 0.0
        for c, rec in K.items():
            if d in rec:
                s += rec[d][4] * rec[d][1]
        amts.append(s)
    amt_pct = float((np.array(amts) < amt).mean() * 100) if amts else 50.0
    vals = np.array(list(chg.values()))
    sh, cyb, ok_idx = fetch_index_chg()
    return dict(day=today, zt_n=zt_n, dt_n=dt_n, max_bd=max_bd, tier_gap=gap,
                earn=earn, promote=promote, amt_pct=amt_pct,
                up_ratio=up/max(n, 1)*100, med_chg=float(np.median(vals)),
                vola=float(np.std(vals)), sh_chg=sh, cyb_chg=cyb,
                index_ok=ok_idx)


def predict(raw, params_path=None):
    p = params_path or os.path.join(BASE, 'mode_params.json')
    P = json.load(open(p, encoding='utf-8'))
    feats = P['feats']
    x = []
    for f in feats:
        v = float(raw.get(f, 0) or 0)
        if f in P.get('log_cols', []):
            v = np.log1p(max(v, 0))
        x.append(v)
    x = np.array(x)
    mu = np.array(P['scaler_mean']); sd = np.array(P['scaler_scale'])
    sd[sd == 0] = 1
    z = (x - mu) / sd
    C = np.array(P['centers'])
    dist = np.linalg.norm(C - z, axis=1)
    i = int(np.argmin(dist))
    label = P['label_map'].get(str(i), 'M%d' % (i+1))
    return dict(mode=label, desc=MODE_DESC.get(label, label),
                dist=float(dist[i]), K=P['K'], raw=raw)


def today_mode(K=None):
    K = K or load_hist()
    raw = compute_raw(K)
    if not raw:
        return None
    return predict(raw)


if __name__ == '__main__':
    r = today_mode()
    print(json.dumps(r, ensure_ascii=False, indent=1))
