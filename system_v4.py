# -*- coding: utf-8 -*-
"""
system_v4.py —— 七层决策引擎（交易模式本体）

流程（严格按 doctrine.md 的顺序）：
  1 判天 regime.classify      → 阶段 + 动作（做/半仓/不做）
  2 纪律 discipline           → 允许开仓? 仓位系数?
  3 模式健康 review_mode      → 模式是否失效? 降档系数?
  4 红线 doctrine.check_all   → 十条逐条检查
  5 选股 four_type            → 按当前阶段挑可用票类
  6 仓位 sizing               → 按该票类在该阶段的赢面定权重
  7 输出 decision.json + 人类可读摘要

输出：_gh_lib/_push_logs/decision_YYYYMMDD.json
"""
import os, sys, json, gzip, pickle
from datetime import datetime, timezone, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
LOG = os.path.join(BASE, '_push_logs')
os.makedirs(LOG, exist_ok=True)
BJ = timezone(timedelta(hours=8))

import regime
import doctrine

# 心法红线2/3（低开不做、高开>7%不追）：逐笔回测显示负贡献 9.3~10.7 个点，
# 故默认关闭；如需只做不追高，改成 True。依据见 doctrine.md 第四节。
GAP_FILTER = False
GAP_LO, GAP_HI = 0.0, 7.0
import discipline
import review_mode
import four_type
import sizing


def load_concept():
    """载入题材映射，排除伪题材"""
    from collections import defaultdict
    p = os.path.join(BASE, '_concept.json')
    if not os.path.exists(p):
        return {}
    CJ = json.load(open(p, encoding='utf-8'))
    EXCL = ['参股', '专精特新', '融资融券', '股权激励', '业绩预', '重组', '重仓', '解禁',
            '分拆', '国企改革', '资产注入', '整体上市', 'ST', '摘帽', '送转', '未股改',
            '三板', '超大盘', '含H股', '含B股', '含GDR', '外资背景', '高校背景', '股期',
            '科创50', '央企50', '社保', '基金', '券商', '信托', '保险', '本地', '成渝',
            '黄河三角', '海峡西岸', '陕甘宁', '长株潭', '皖江', '雄安', '京津冀',
            '海南自贸', '武汉规划', '沿海发展', '前海', '图们江', '自贸', '振兴沈阳',
            '海上丝路', '三沙', '水域改革', '朝鲜改革', '迪士尼', '本月', '沪股通',
            '深股通', 'MSCI', '标普', '富时', '转融券', '融资']
    m = defaultdict(list)
    for node, codes in CJ.get('concepts', {}).items():
        if any(x in CJ.get('names', {}).get(node, '') for x in EXCL):
            continue
        for c in codes:
            m[c].append(node)
    return m


def load_hist():
    with gzip.open(os.path.join(BASE, '_hist.pkl.gz'), 'rb') as f:
        return pickle.load(f)


def market_state(K):
    """算今日 12 维中的关键 4 项：涨停/跌停/最高板/赚钱效应"""
    days = sorted({d for v in K.values() for d in v})
    if len(days) < 3:
        return None
    today, prev = days[-1], days[-2]
    chg, zt, bd = {}, {}, {}
    for c, rec in K.items():
        if today in rec and prev in rec and rec[prev][1] > 0:
            chg[c] = (rec[today][1] / rec[prev][1] - 1) * 100
        ds = sorted(rec)
        i = len(ds) - 1
        run = 0
        for j in range(i, max(i - 12, -1), -1):
            d = ds[j]
            if j == 0:
                break
            p = rec[ds[j - 1]][1]
            if p > 0 and 9.8 <= (rec[d][1] / p - 1) * 100 <= 10.6:
                run += 1
            else:
                break
        if today in rec and run:
            bd[c] = run
    if not chg:
        return None
    dt_n = sum(1 for v in chg.values() if v <= -9.8)
    # 赚钱效应：昨日涨停股在今日的平均涨幅（昨日=ds[-2]，今日=ds[-1]）
    pzt = []
    for c, rec in K.items():
        ds = sorted(rec)
        if len(ds) < 3:
            continue
        p_prev2 = rec[ds[-3]][1]
        if p_prev2 > 0 and 9.8 <= (rec[ds[-2]][1] / p_prev2 - 1) * 100 <= 10.6:
            pzt.append(c)
    earn = None
    if len(pzt) >= 10:
        vals = [chg[c] for c in pzt if c in chg]
        if vals:
            earn = sum(vals) / len(vals)
    return dict(day=today, zt_n=len(bd), dt_n=dt_n,
                max_bd=max(bd.values()) if bd else 0,
                earn=earn if earn is not None else 0.0)


def pick_candidates(K, stage):
    """按阶段挑可用票类，从当日数据算候选"""
    days = sorted({d for v in K.values() for d in v})
    today, prev = days[-1], days[-2]
    out = []
    # 当日最高板（用于识别龙头）
    bd_today = {}
    for c, rec in K.items():
        ds = sorted(rec)
        if len(ds) < 2:
            continue
        p = rec[ds[-2]][1]
        if p > 0 and 9.8 <= (rec[ds[-1]][1] / p - 1) * 100 <= 10.6:
            run = 1
            j = len(ds) - 2
            while j >= 1:
                p2 = rec[ds[j - 1]][1]
                if p2 > 0 and 9.8 <= (rec[ds[j]][1] / p2 - 1) * 100 <= 10.6:
                    run += 1
                    j -= 1
                else:
                    break
            bd_today[c] = run
    mx = max(bd_today.values()) if bd_today else 0
    # 当日题材涨停家数与排名（真实数据，非占位）
    from collections import defaultdict
    code2con = load_concept()
    con_zt = defaultdict(int)
    for c in bd_today:
        for node in code2con.get(c, []):
            con_zt[node] += 1
    rank_map = {}
    for i, (node, _cnt) in enumerate(sorted(con_zt.items(), key=lambda x: -x[1]), 1):
        rank_map[node] = i
    for c, rec in K.items():
        ds = sorted(rec)
        if len(ds) < 60 or ds[-1] != today:
            continue
        C = [rec[d][1] for d in ds]
        O = [rec[d][0] for d in ds]
        H = [rec[d][2] for d in ds]
        L = [rec[d][3] for d in ds]
        V = [rec[d][4] for d in ds]
        chg = (C[-1] / C[-2] - 1) * 100 if len(C) >= 2 and C[-2] > 0 else 0.0
        i = len(ds) - 1
        ma5 = sum(C[-5:]) / 5
        ma10 = sum(C[-10:]) / 10
        ma20 = sum(C[-20:]) / 20
        v20 = sum(V[-20:]) / 20
        amp = (H[-1] - L[-1]) / C[-2] * 100 if C[-2] > 0 else 0
        gap5 = (C[-1] / (sum(C[-6:-1]) / 5) - 1) * 100 if sum(C[-6:-1]) > 0 else 0
        bdv = bd_today.get(c, 0)
        p60 = sum(1 for x in C[-60:] if x < C[-1]) / 60 * 100
        tp, sell, why, seg_factor, seg_note = None, None, '', 1.0, ''
        # 段可用性由三段验证结果决定（four_type.allowed），不再用硬编码 stages
        if bdv >= 3 and bdv == mx:
            ok, fac, note = four_type.allowed('龙头', stage)
            if ok:
                tp, sell, seg_factor, seg_note = '龙头', four_type.TYPES['龙头']['sell'], fac, note
                why = '%d板龙头（最高板）' % bdv
        if not tp and 2 <= bdv <= 3:
            ok, fac, note = four_type.allowed('前排', stage)
            if ok:
                tp, sell, seg_factor, seg_note = '前排', four_type.TYPES['前排']['sell'], fac, note
                why = '%d板前排' % bdv
        if not tp and bdv == 1 and p60 < 40:
            ok, fac, note = four_type.allowed('补涨', stage)
            if ok:
                tp, sell, seg_factor, seg_note = '补涨', four_type.TYPES['补涨']['sell'], fac, note
                why = '低位首板（60日分位%.0f）' % p60
        if not tp and (amp <= 1.849 and (V[-1] / v20 if v20 > 0 else 9) <= 0.609
                       and gap5 > 1.802 and chg > 1.63):
            ok, fac, note = four_type.allowed('趋势', stage)
            if ok:
                tp, sell, seg_factor, seg_note = '趋势', four_type.TYPES['趋势']['sell'], fac, note
                why = '缩量窄幅（振幅%.2f%% 量比%.2f）' % (amp, V[-1] / v20 if v20 > 0 else 0)
        if not tp:
            continue
        nodes = code2con.get(c, [])
        if nodes:
            best = max(nodes, key=lambda n: con_zt.get(n, 0))
            t_zt, t_rank = con_zt.get(best, 0), rank_map.get(best, 99)
            t_name = best
        else:
            t_zt, t_rank, t_name = 0, 99, ''
        out.append(dict(code=c, type=tp, sell=sell, why=why,
                        close=round(C[-1], 2), buy_price=round(C[-1], 2),
                        chg=round(chg, 2), amp=round(amp, 2), bd=bdv,
                        theme_zt=t_zt, theme_rank=t_rank, theme=t_name,
                        seg_factor=seg_factor, seg_note=seg_note))
    return out


def main():
    dry = '--dry' in sys.argv
    now = datetime.now(BJ)
    print('=== system_v4 %s ===' % now.strftime('%Y-%m-%d %H:%M'), flush=True)

    K = load_hist()
    ms = market_state(K)
    if not ms:
        print('数据不足，退出', flush=True)
        return
    print('环境：涨停 %.0f / 跌停 %.0f / 最高 %.0f 板 / 赚钱 %+.2f%%（基准日 %s）' % (
        ms['zt_n'], ms['dt_n'], ms['max_bd'], ms['earn'], ms['day']), flush=True)

    stage, action, why = regime.classify(ms['zt_n'], ms['dt_n'], ms['max_bd'], ms['earn'])
    p = regime.params(action)
    print('判天：%s → %s（%s）' % (stage, action, why), flush=True)

    allow, blocks, d_factor = discipline.check_before_open()
    print('纪律：%s %s 系数%.1f' % ('允许' if allow else '拦截', blocks, d_factor), flush=True)

    m_factor, m_verdict = review_mode.get_factor()
    print('模式健康：系数%.1f（%s）' % (m_factor, m_verdict), flush=True)

    if action == '不做' or not allow or m_factor == 0:
        print('', flush=True)
        print('结论：今日空仓', flush=True)
        for b in blocks:
            print('  -', b, flush=True)
        out = dict(day=ms['day'], stage=stage, action='不做', reason=why,
                   blocks=blocks, picks=[], max_weight=0, max_picks=0)
        fp = os.path.join(LOG, 'decision_%s.json' % now.strftime('%Y%m%d'))
        json.dump(out, open(fp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('已写', fp, flush=True)
        return

    cand = pick_candidates(K, stage)
    print('候选：%d 只（阶段 %s 允许的票类）' % (len(cand), stage), flush=True)

    sized = []
    for x in cand:
        w, deq, wreason = sizing.weight_for(x['type'], stage)
        if w <= 0:
            continue
        w = (min(w, p['weight']) * d_factor * m_factor
             * float(x.get('seg_factor', 1.0)))   # 三段验证降档系数
        st_disc = discipline.load()
        ctx = dict(theme_rank=x.get('theme_rank', 99), theme_zt=x.get('theme_zt', 0),
                   gap_pct=None, one_word=False,
                   regime_action=action, sell_rule=x['sell'], weight=w,
                   positions=len(sized) + 1,
                   loss_streak=st_disc.get('loss_streak'),
                   daily_pnl=st_disc.get('last_daily_pnl'),
                   mode=st_disc.get('mode', 'four_type'))
        ok, blks = doctrine.check_all(ctx)
        sized.append(dict(x, weight=round(w, 4), deq=deq, sizing_reason=wreason,
                          doctrine_ok=ok, doctrine_blocks=[b['reason'] for b in blks]))

    sized.sort(key=lambda z: (-(z['deq'] or 0), -z['weight']))
    picks = sized[:p['max_picks']]
    print('', flush=True)
    print('=== 决策：%s %d 只（单票上限 %.0f%%）===' % (action, len(picks), p['weight'] * 100), flush=True)
    for x in picks:
        print('  %s %-4s %-6s 权重%.0f%% | %s | 题材:%s(涨停%d,第%d) | %s' % (
            x['code'], x['type'], x['sell'], x['weight'] * 100, x['why'],
            x.get('theme', '') or '无', x.get('theme_zt', 0), x.get('theme_rank', 99),
            '通过' if x['doctrine_ok'] else '拦截:' + ';'.join(x['doctrine_blocks'])), flush=True)

    out = dict(day=ms['day'], stage=stage, action=action, reason=why,
               env=ms, blocks=blocks, discipline_factor=d_factor,
               mode_factor=m_factor, max_weight=p['weight'], max_picks=p['max_picks'],
               picks=picks)
    fp = os.path.join(LOG, 'decision_%s.json' % now.strftime('%Y%m%d'))
    json.dump(out, open(fp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('', flush=True)
    print('已写', fp, flush=True)


if __name__ == '__main__':
    main()
