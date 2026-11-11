# -*- coding: utf-8 -*-
"""
live_fetch.py —— 历史缓存 + 当日增量（云端快、本地可全量重建）

优先级：
  1. 若 _hist.pkl.gz 存在 → 读历史，用腾讯批量行情（60只/批）抓当日 OHLCV 增量合并
  2. 否则 → 新浪全量抓 260 根（仅首次/本地重建用）

腾讯量单位是「手」，新浪是「股」，统一 ×100。
"""
import os, json, time, urllib.request, pickle, glob, gzip
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = os.path.dirname(os.path.abspath(__file__))
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
HIST = os.path.join(BASE, '_hist.pkl.gz')
LIVE = os.path.join(BASE, '_live_kline.pkl')


def get_codes():
    p = os.path.join(BASE, 'universe.json')
    if os.path.exists(p):
        return sorted(json.load(open(p, encoding='utf-8')))
    return sorted({os.path.basename(f).replace('.pkl', '')
                   for f in glob.glob(os.path.join(BASE, '_kline_raw', '*.pkl'))})


def http(url, enc='gbk', timeout=15):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                  timeout=timeout).read().decode(enc, errors='ignore')


# ---------- 增量：腾讯批量行情 ----------
def tencent_snapshot(codes):
    out = {}
    def one(chunk):
        q = ','.join(('sh' if c.startswith(('6', '5')) else 'sz') + c for c in chunk)
        for k in range(2):
            try:
                txt = http('https://qt.gtimg.cn/q=' + q)
                res = {}
                for line in txt.split(';'):
                    if '=' not in line:
                        continue
                    f = line.split('=', 1)[1].strip('"').split('~')
                    if len(f) < 40 or not f[2]:
                        continue
                    try:
                        c = f[2]
                        o, cl, hi, lo = float(f[5]), float(f[3]), float(f[33]), float(f[34])
                        vol = float(f[6]) * 100.0          # 手 → 股
                        stamp = str(f[30])[:8]
                        day = '%s-%s-%s' % (stamp[:4], stamp[4:6], stamp[6:8])
                        if o > 0 and cl > 0:
                            res[c] = (day, (o, cl, hi, lo, vol))
                    except Exception:
                        continue
                return res
            except Exception:
                time.sleep(0.3)
        return {}
    chunks = [codes[i:i + 60] for i in range(0, len(codes), 60)]
    with ThreadPoolExecutor(max_workers=8) as ex:
        for f in as_completed([ex.submit(one, c) for c in chunks]):
            out.update(f.result())
    return out


# ---------- 全量：新浪 260 根 ----------
def sina_full(codes):
    def one(c):
        sym = ('sh' if c.startswith(('6', '5')) else 'sz') + c
        u = ('https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketData.getKLineData'
             '?symbol=%s&scale=240&ma=no&datalen=260' % sym)
        for k in range(2):
            try:
                a = json.loads(http(u, 'utf-8', 15))
                if not a:
                    return c, None
                return c, {str(x['day'])[:10]: (float(x['open']), float(x['close']),
                                                float(x['high']), float(x['low']),
                                                float(x['volume'])) for x in a}
            except Exception:
                time.sleep(0.25)
        return c, None
    res = {}
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=10) as ex:
        for i, f in enumerate(as_completed([ex.submit(one, c) for c in codes])):
            c, v = f.result()
            if v:
                res[c] = v
            if (i + 1) % 500 == 0:
                print('  %d/%d 成功%d 用时%.0fs' % (i + 1, len(codes), len(res), time.time() - t0), flush=True)
    return res


def main():
    codes = get_codes()
    t0 = time.time()
    if os.path.exists(HIST):
        print('读历史缓存 %.1f MB' % (os.path.getsize(HIST) / 1048576), flush=True)
        with gzip.open(HIST, 'rb') as f:
            K = pickle.load(f)
        snap = tencent_snapshot(codes)
        days = [v[0] for v in snap.values() if v[0][:2] == '20']
        today = max(days) if days else None
        print('腾讯快照 %d 只，交易日 %s，用时 %.0fs' % (len(snap), today, time.time() - t0), flush=True)
        if not today:
            print('无有效快照，沿用历史最新日', flush=True)
            today = max({d for v in K.values() for d in v})
        else:
            added = 0
            for c, (day, bar) in snap.items():
                if c not in K:
                    K[c] = {}
                if day not in K[c]:
                    added += 1
                K[c][day] = bar
                if len(K[c]) > 265:
                    for d in sorted(K[c])[:len(K[c]) - 260]:
                        del K[c][d]
            print('合并当日记录 %d 条' % added, flush=True)
    else:
        print('无历史缓存 → 新浪全量抓取（首次约 2 分钟）', flush=True)
        K = sina_full(codes)

    pickle.dump(K, open(LIVE, 'wb'), protocol=4)
    with gzip.open(HIST, 'wb', compresslevel=6) as f:
        pickle.dump(K, f, protocol=4)
    all_days = {d for v in K.values() for d in v}
    print('完成 %d 只 / 最新交易日 %s / 缓存 %.1f MB / 用时 %.0fs' % (
        len(K), max(all_days), os.path.getsize(HIST) / 1048576, time.time() - t0), flush=True)


if __name__ == '__main__':
    main()
