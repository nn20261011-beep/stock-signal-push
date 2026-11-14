# -*- coding: utf-8 -*-
"""
sizing.py —— 按赢面分档决定单票权重

赢面来源：four_type 的 type×stage 日等权（2016-2026 回测）。
分档规则（不是拍脑袋，按日等权绝对值分四档）：
  日等权 >= 4%  → 10%
  2% <= deq < 4% → 8%
  0% <= deq < 2% → 6%
  deq < 0        → 不做
"""
import os, json

BASE = os.path.dirname(os.path.abspath(__file__))
STATS = os.path.join(BASE, 'type_stage_stats.json')

# 无历史统计时的兜底（保守）
FALLBACK = {'龙头': 0.10, '趋势': 0.08, '前排': 0.06, '补涨': 0.06}


def load_stats():
    if os.path.exists(STATS):
        try:
            return json.load(open(STATS, encoding='utf-8'))
        except Exception:
            pass
    return {}


def weight_for(tp, stage):
    """返回 (weight, deq, reason)"""
    st = load_stats()
    key = '%s|%s' % (tp, stage)
    rec = st.get(key)
    if not rec:
        w = FALLBACK.get(tp, 0.05)
        return w, None, '无该阶段统计，用兜底 %.0f%%' % (w * 100)
    deq = float(rec.get('deq', 0))
    if deq >= 4.0:
        w = 0.10
    elif deq >= 2.0:
        w = 0.08
    elif deq >= 0.0:
        w = 0.06
    else:
        return 0.0, deq, '该阶段日等权 %.2f%% < 0，不做' % deq
    cap = rec.get('max_weight')
    if cap:
        w = min(w, float(cap))
    return w, deq, '日等权 %.2f%% → 单票 %.0f%%' % (deq, w * 100)


def selftest():
    # 造一份临时统计
    tmp = {
        '龙头|高潮': {'deq': 4.87},
        '龙头|发酵': {'deq': 2.78},
        '前排|启动': {'deq': 0.94},
        '补涨|启动': {'deq': -1.29},
    }
    json.dump(tmp, open(STATS, 'w', encoding='utf-8'), ensure_ascii=False)
    cases = [
        ('龙头', '高潮', 0.10), ('龙头', '发酵', 0.08),
        ('前排', '启动', 0.06), ('补涨', '启动', 0.0),
    ]
    ok = 0
    for tp, stg, exp in cases:
        w, deq, why = weight_for(tp, stg)
        hit = abs(w - exp) < 1e-9
        ok += hit
        print('  %-4s×%-4s → %.0f%%（期望 %.0f%%）%s' % (tp, stg, w * 100, exp * 100, '✅' if hit else '❌'))
    print('')
    print('自检 %d/%d' % (ok, len(cases)))
    return ok == len(cases)


if __name__ == '__main__':
    raise SystemExit(0 if selftest() else 1)
