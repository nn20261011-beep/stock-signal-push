# -*- coding: utf-8 -*-
"""
bt_engine.py —— 参数化回测引擎（数据只加载一次，可反复跑不同参数）

与 bt_v4_full.py 的区别：判天阈值、题材阈值、仓位、纪律全部参数化，
用于「回测→修正→再回测」迭代寻优。
"""
import os, sys, glob, pickle
import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))   # backtest/
ROOT = BASE                                          # 数据都在 backtest/ 下
sys.path.insert(0, os.path.join(BASE, '_gh_lib'))

DEFAULT = dict(
    entry='open',            # open | seal
    ret_col='sl5',           # r1 | rbreak | sl5 | r10
    theme_min=2,             # 题材涨停家数下限
    weight_cap=0.10,         # 单票上限
    max_pos=8,               # 最多持仓
    exposure=0.80,           # 总仓上限
    streak_limit=3,          # 连亏几笔停手
    halt_dd=-20.0,           # 回撤熔断
    halt_days=20,            # 熔断空仓天数
    mode_stop=-3.0,          # 近20笔均值低于此值停手
    mode_cool=5,             # 停手冷却天数
    zt_lo=20, zt_hi=55,      # 涨停数分档：<lo 冰点/退潮，>hi 高潮
    earn_lo=-1.0, earn_hi=1.0,   # 赚钱效应分档
    maxbd_hi=6,              # 最高板高位分界
    hold_map=None,           # 各票类持有天数
    slippage=0.0,            # 每笔滑点+费用（%），压力测试用
)


class Engine:
    def __init__(self):
        print('[engine] 载入数据...', flush=True)
        E = pd.read_pickle(os.path.join(ROOT, '_events3.pkl'))
        E = E[E['day'] >= '2016-01-01'].copy()
        import four_type
        mx = E.groupby('day')['bd'].max().to_dict()
        E['type'] = four_type.tag(E, mx)
        E = E[E['type'] != '']
        self.byday = {d: g for d, g in E.groupby('day')}
        M = pd.read_pickle(os.path.join(ROOT, '_regime_base.pkl'))
        self.env = {r['day']: (r['zt_n'], r['dt_n'], r['max_bd'], r['earn'])
                    for _, r in M.iterrows()}
        self.days = sorted(E['day'].unique())
        K = {}
        for fp in glob.glob(os.path.join(ROOT, '_kline_raw', '*.pkl')):
            c = os.path.basename(fp).replace('.pkl', '')
            try:
                K[c] = pickle.load(open(fp, 'rb'))
            except Exception:
                pass
        self.K = K
        self.IDX = {}
        for c, rec in K.items():
            ds = sorted(rec)
            self.IDX[c] = (ds, {d: j for j, d in enumerate(ds)})
        self.MF = {}
        mfp = os.path.join(ROOT, '_minfeat2.pkl')
        if os.path.exists(mfp):
            try:
                self.MF = pickle.load(open(mfp, 'rb'))
            except Exception:
                pass
        # 各票类在该参数下的可用性（沿用三段验证结果，参数化前先固定）
        self.hold = dict(龙头=3, 前排=3, 趋势=5, 补涨=10)
        print('[engine] %d 行 / %d 天 / %d 只 / 分钟特征 %d 只' % (
            len(E), len(self.days), len(K), len(self.MF)), flush=True)

    # ---------- 判天（参数化） ----------
    def classify(self, zt, dt, mb, earn, p):
        if zt is None or earn is None:
            return '未知', '不做'
        if zt < p['zt_lo'] and earn > p['earn_hi']:
            return '退潮', '不做'
        if zt < p['zt_lo'] and earn <= p['earn_hi']:
            return '冰点', '半仓'
        if zt > p['zt_hi'] and earn > p['earn_hi']:
            return '高潮', '做'
        if zt > p['zt_hi'] and p['earn_lo'] <= earn <= p['earn_hi']:
            return '高潮分化', '半仓'
        if p['zt_lo'] <= zt <= p['zt_hi'] and earn > p['earn_lo']:
            return '发酵', '做'
        if p['zt_lo'] <= zt <= p['zt_hi']:
            return '发酵转弱', '半仓'
        return '震荡', '半仓'

    def params_of(self, act, p):
        if act == '做':
            return p['exposure'], p['max_pos']
        if act == '半仓':
            return p['exposure'] * 0.25, max(1, p['max_pos'] // 2)
        return 0.0, 0

    def seal_trade(self, code, sig_day, maxhold=10):
        if code not in self.IDX:
            return None
        ds, pos = self.IDX[code]
        rec = self.K[code]
        i = pos.get(sig_day)
        if i is None or i + 1 >= len(ds):
            return None
        nd = ds[i + 1]
        limit = round(rec[ds[i]][1] * 1.1, 2)
        mf = self.MF.get(code, {}).get(nd)
        if not mf or mf.get('zt_touch') != 1:
            return None
        if abs(rec[nd][0] - limit) < 0.011:
            return None
        buy = limit
        for k in range(i + 1, min(i + 1 + maxhold, len(ds) - 1)):
            d = ds[k]
            chg = (rec[d][1] / rec[ds[k - 1]][1] - 1) * 100 if k > 0 else 0
            if not (9.8 <= chg <= 10.6):
                kk = min(k + 1, len(ds) - 1)
                return (rec[ds[kk]][1] / buy - 1) * 100 - 0.1, kk - i
        kk = min(i + 1 + maxhold, len(ds) - 1)
        return (rec[ds[kk]][1] / buy - 1) * 100 - 0.1, kk - i

    def run(self, start=None, end=None, **kw):
        p = dict(DEFAULT)
        p.update(kw)
        days = [d for d in self.days
                if (not start or d >= start) and (not end or d <= end)]
        cash = 1.0
        pos = []
        nav = []
        peak = 1.0
        halt_left = 0
        mode_cool = 0
        trades = 0
        wins = 0
        loss_streak = 0
        recent = []
        day_cost = 0.0
        day_pnl = 0.0
        last_daily = 0.0
        daily_half = False
        for i, d in enumerate(days):
            keep = []
            for sd, v, win, c0 in pos:
                if sd <= i:
                    cash += v
                    day_cost += c0
                    day_pnl += (v - c0)
                    if win:
                        wins += 1
                else:
                    keep.append((sd, v, win, c0))
            pos = keep
            if day_cost > 0:
                pnl_pct = day_pnl / day_cost * 100
                loss_streak = loss_streak + 1 if pnl_pct < 0 else 0
                last_daily = pnl_pct
                day_cost = 0.0
                day_pnl = 0.0
            if loss_streak >= p['streak_limit']:
                loss_streak = 0
                nav.append(cash + sum(v for _, v, _, _ in pos))
                continue
            daily_half = last_daily <= -5.0
            cur = cash + sum(v for _, v, _, _ in pos)
            peak = max(peak, cur)
            if cur / peak - 1 <= p['halt_dd'] / 100:
                halt_left = p['halt_days']
            if halt_left > 0:
                halt_left -= 1
                nav.append(cur)
                continue
            if d not in self.env:
                nav.append(cur)
                continue
            st, act = self.classify(*self.env[d], p)
            if act == '不做':
                nav.append(cur)
                continue
            if mode_cool > 0:
                mode_cool -= 1
                nav.append(cur)
                continue
            if len(recent) >= 10:
                avg = sum(recent[-20:]) / len(recent[-20:])
                if avg <= p['mode_stop']:
                    mode_cool = p['mode_cool']
                    recent = []
                    nav.append(cur)
                    continue
                if avg < 0:
                    daily_half = True
            g = self.byday.get(d)
            if g is None or not len(g):
                nav.append(cur)
                continue
            # 阶段 → 可用票类（与 bt_v4_full 同口径，保证可比）
            import four_type as _ft
            usable = [tp for tp in _ft.TYPES if st in _ft.TYPES[tp]['stages']]
            cand = g[g['type'].isin(usable)]
            if not len(cand):
                nav.append(cur)
                continue
            if 'c_zt' in cand.columns:
                cand = cand[cand['c_zt'] >= p['theme_min']]
            if not len(cand):
                nav.append(cur)
                continue
            exp, maxn = self.params_of(act, p)
            if daily_half:
                exp *= 0.5
            cand = cand.sort_values('chg', ascending=False)
            picks = cand.head(maxn)
            per = min(p['weight_cap'], exp / max(len(picks), 1), cash / max(len(picks), 1))
            if per <= 0.001:
                nav.append(cur)
                continue
            for _, r in picks.iterrows():
                c = r['code']
                if p['entry'] == 'seal':
                    t = self.seal_trade(c, d)
                    if not t:
                        continue
                    ret, hd = t
                    ret -= p['slippage']
                else:
                    col = p['ret_col'] if p['ret_col'] in r.index else 'r1'
                    ret = float(r[col]) - p['slippage']
                    if not np.isfinite(ret):
                        continue
                    hd = int(self.hold.get(r['type'], 2))
                amt = per
                if amt > cash:
                    continue
                cash -= amt
                pos.append((i + hd, amt * (1 + ret / 100), ret > 0, amt))
                trades += 1
                recent.append(ret)
            nav.append(cash + sum(v for _, v, _, _ in pos))
        nav = np.array(nav)
        pk = np.maximum.accumulate(nav)
        ann = (nav[-1] ** (240 / len(nav)) - 1) * 100 if nav[-1] > 0 else -99
        mdd = ((nav / pk) - 1).min() * 100
        return dict(nav=float(nav[-1]), ann=float(ann), mdd=float(mdd),
                    calmar=float(ann / abs(mdd)) if mdd < 0 else 99.0,
                    trades=int(trades), win=float(wins / trades * 100) if trades else 0.0,
                    days=len(nav))


if __name__ == '__main__':
    e = Engine()
    r = e.run()
    print('基准（默认参数）：净值%.2f 年化%+.1f%% 回撤%.1f%% Calmar%.2f 笔%d 胜率%.1f%%' % (
        r['nav'], r['ann'], r['mdd'], r['calmar'], r['trades'], r['win']))
