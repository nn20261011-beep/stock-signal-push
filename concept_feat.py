# -*- coding: utf-8 -*-
"""云端实时题材/身位特征计算
读 _hist.pkl.gz + _concept.json，输出每只票最新交易日的 7 个题材特征。
只回溯最近 25 个交易日（c_first 判定需要 20 日窗口），速度快。
"""
import os, gzip, pickle, json
import numpy as np

BASE = os.path.dirname(os.path.abspath(__file__))
ZT_LO, ZT_HI = 9.8, 10.6

EXCLUDE_KW = ['参股', '专精特新', '融资融券', '股权激励', '业绩预', '重组', '金融参股',
              '重仓', '解禁', '分拆', '国企改革', '资产注入', '整体上市', 'ST', '摘帽',
              '送转', '未股改', '三板', '超大盘', '含H股', '含B股', '含GDR', '外资背景',
              '高校背景', '股期', '科创50', '央企50', '社保', '基金', '券商', '信托', '保险',
              '上海本地', '成渝', '黄河三角', '海峡西岸', '陕甘宁', '长株潭', '深圳本地',
              '皖江', '雄安', '京津冀', '海南自贸', '武汉规划', '沿海发展', '前海',
              '图们江', '上海自贸', '东亚自贸', '自贸区', '振兴沈阳', '海上丝路',
              '三沙', '天津自贸', '水域改革', '朝鲜改革', '迪士尼', '本月', '沪股通',
              '深股通', 'MSCI', '标普', '富时', '转融券', '融资']


def compute(K, out_path=None):
    cp = os.path.join(BASE, '_concept.json')
    if not os.path.exists(cp):
        return {}
    CJ = json.load(open(cp, encoding='utf-8'))
    concepts = {k: v for k, v in CJ['concepts'].items()
                if not any(x in CJ['names'][k] for x in EXCLUDE_KW)}
    code2con = {}
    for node, codes in concepts.items():
        for c in codes:
            code2con.setdefault(c, []).append(node)

    # 每只票的日期序列与涨幅/连板
    days = sorted({d for v in K.values() for d in v})
    recent = days[-25:]
    chg, zt, bdmap = {}, {}, {}
    for c, v in K.items():
        ds = sorted(v.keys())
        C = np.array([v[d][1] for d in ds], float)
        CH = np.zeros(len(ds))
        CH[1:] = (C[1:] / np.maximum(C[:-1], 1e-9) - 1) * 100
        run = 0
        for i, d in enumerate(ds):
            if d not in recent:
                continue
            chg.setdefault(d, {})[c] = float(CH[i])
            if ZT_LO <= CH[i] <= ZT_HI:
                run += 1
                zt.setdefault(d, {})[c] = 1
                bdmap.setdefault(d, {})[c] = run
            else:
                run = 0

    # 每日每概念强度：涨停数、均涨、最高板
    con_day = {}
    for d in recent:
        ztd, chd = zt.get(d, {}), chg.get(d, {})
        for node, codes in concepts.items():
            zs = [c for c in codes if c in ztd]
            if not zs:
                continue
            vals = [chd[c] for c in codes if c in chd]
            con_day[(d, node)] = (len(zs), float(np.mean(vals)) if vals else 0.0,
                                  max(bdmap[d].get(c, 1) for c in zs))
    # 首次活跃（近 20 日无涨停）
    first = {}
    last = {}
    for d in recent:
        for node in concepts:
            if (d, node) in con_day:
                p = last.get(node)
                if p is None or (recent.index(d) - recent.index(p) > 20):
                    first[(d, node)] = 1
                last[node] = d

    today = recent[-1]
    out = {}
    for c in K:
        ds = sorted(K[c].keys())
        if today not in ds:
            continue
        i = ds.index(today)
        C = np.array([K[c][d][1] for d in ds], float)
        my5 = (C[i] / C[i - 5] - 1) * 100 if i >= 5 and C[i - 5] > 0 else 0.0
        cons = code2con.get(c, [])
        best_zt, best_chg, best_first, rank, gap, hot = 0, 0.0, 0, 9, 0.0, 0
        for node in cons:
            rec = con_day.get((today, node))
            if not rec:
                continue
            zn, ac, mb = rec
            hot += 1
            if zn > best_zt:
                best_zt, best_chg = zn, ac
                best_first = first.get((today, node), 0)
                mybd = bdmap.get(today, {}).get(c, 0)
                rank = 1 + sum(1 for x in concepts[node]
                               if bdmap.get(today, {}).get(x, 0) > mybd)
                leader = None
                lmax = -1
                for x in concepts[node]:
                    b = bdmap.get(today, {}).get(x, 0)
                    if b > lmax:
                        lmax, leader = b, x
                if leader and leader in K and today in K[leader]:
                    ld = sorted(K[leader].keys())
                    li = ld.index(today)
                    LC = np.array([K[leader][d][1] for d in ld], float)
                    l5 = (LC[li] / LC[li - 5] - 1) * 100 if li >= 5 and LC[li - 5] > 0 else 0.0
                    gap = my5 - l5
        out[c] = dict(c_zt=int(best_zt), c_chg=float(best_chg), c_first=int(best_first),
                      c_rank=int(min(rank, 9)), c_gap=float(gap),
                      c_hot=int(hot), c_n=int(len(cons)))
    if out_path:
        json.dump(dict(day=today, features=out), open(out_path, 'w', encoding='utf-8'),
                  ensure_ascii=False)
    return out


if __name__ == '__main__':
    with gzip.open(os.path.join(BASE, '_hist.pkl.gz'), 'rb') as f:
        K = pickle.load(f)
    r = compute(K, os.path.join(BASE, '_concept_feat.json'))
    print('概念特征 %d 只 / 基准日 %s' % (len(r), max({d for v in K.values() for d in v})))
    vals = list(r.values())
    print('  c_zt 均值%.2f / c_hot 均值%.2f / c_rank 均值%.2f' % (
        np.mean([x['c_zt'] for x in vals]), np.mean([x['c_hot'] for x in vals]),
        np.mean([x['c_rank'] for x in vals])))
