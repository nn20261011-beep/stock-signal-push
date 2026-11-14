# -*- coding: utf-8 -*-
"""
four_type.py —— 四类票分型与各自买卖点

四类（不是拍脑袋，按 A 股资金结构分）：
  龙头：当日最高板（bd==max_bd 且 >=3），主线所属
  前排：2-3 板，非最高板
  补涨：首板 + 位置低（60日分位<40）
  趋势：缩量窄幅（振幅<=1.85% & 量比<=0.609 & 距MA5>1.8% & 当日涨>1.63%）

每类绑定：适用情绪阶段、买点、卖点、仓位上限
"""
import pandas as pd
import numpy as np

# 四类票的配置（阶段适用范围由 2016-2026 分阶段回测确定，见 __main__ 输出）
# 龙头：全阶段为正（高潮+4.87 / 冰点+4.15 / 启动+3.95 / 发酵+2.78）
# 趋势：全阶段为正（发酵+5.95 / 启动+5.51 / 高潮+4.84），但胜率仅33-39%，靠右尾
# 前排：仅启动+0.94 / 高潮+0.43 / 高潮分化+0.44；冰点-0.03、发酵转弱-1.51 → 弱市禁用
# 补涨：仅高潮+0.72（胜率63.7%）；启动-1.29、冰点-1.70、高潮分化-3.78 → 只在高潮用
TYPES = {
    '龙头': dict(stages=['高潮', '冰点', '启动', '发酵', '高潮分化', '发酵转弱', '震荡'],
                entry='竞价高开0-7%', sell='rbreak',
                max_weight=0.10, note='最高板，断板次日走'),
    '趋势': dict(stages=['高潮', '冰点', '启动', '发酵', '高潮分化', '发酵转弱', '震荡'],
                entry='次日开盘', sell='sl5',
                max_weight=0.10, note='缩量窄幅，止损5%'),
    '前排': dict(stages=['启动', '高潮', '高潮分化'],
                entry='竞价高开0-7%', sell='rbreak',
                max_weight=0.08, note='2-3板，弱市禁用'),
    '补涨': dict(stages=['高潮'],
                entry='次日开盘', sell='r10',
                max_weight=0.06, note='低位首板，只在高潮期用'),
}


def tag(df, max_bd_by_day):
    """给事件池打上四类标签"""
    out = pd.Series('', index=df.index)
    mx = df['day'].map(max_bd_by_day).fillna(0)
    # 龙头
    m = (df['bd'] >= 3) & (df['bd'] == mx) & (df['is_zt'] == 1)
    out[m] = '龙头'
    # 前排
    m2 = (df['bd'].between(2, 3)) & (df['is_zt'] == 1) & (out == '')
    out[m2] = '前排'
    # 补涨
    m3 = (df['bd'] == 1) & (df['is_zt'] == 1) & (df['p60'] < 40) & (out == '')
    out[m3] = '补涨'
    # 趋势
    m4 = ((df['amp'] <= 1.849) & (df['vol_r'] <= 0.609) & (df['gap5'] > 1.802)
          & (df['chg'] > 1.63) & (out == ''))
    out[m4] = '趋势'
    return out


def evaluate(df, stage_series):
    """
    df: 含 day/type/r5/sl5/r10/rbreak/... 的事件表
    stage_series: index=day, value=情绪阶段
    返回：类型 × 阶段 的统计
    """
    d = df.copy()
    d['stage'] = d['day'].map(stage_series).fillna('未知')
    rows = []
    for t, g in d.groupby('type'):
        for st, gg in g.groupby('stage'):
            if len(gg) < 100:
                continue
            sell = TYPES[t]['sell']
            col = sell if sell in gg.columns else 'r5'
            daily = gg.groupby('day')[col].mean()
            vals = gg[col]
            rows.append(dict(type=t, stage=st, n=len(gg), days=daily.size,
                             deq=round(daily.mean(), 3),
                             mean=round(vals.mean(), 3),
                             win=round((vals > 0).mean() * 100, 1)))
    return pd.DataFrame(rows).sort_values(['type', 'deq'], ascending=[True, False])


if __name__ == '__main__':
    import os, sys
    BASE = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, BASE)
    import regime
    E = pd.read_pickle(os.path.join(BASE, '..', '_events3.pkl'))
    E = E[E['day'] >= '2016-01-01']
    mx = E.groupby('day')['bd'].max().to_dict()
    E['type'] = tag(E, mx)
    print('四类票分布：')
    print(E['type'].value_counts().to_string())
    # 情绪阶段
    M = pd.read_pickle(os.path.join(BASE, '..', '_regime_base.pkl'))
    st = {}
    for _, r in M.iterrows():
        s, a, _w = regime.classify(r['zt_n'], r['dt_n'], r['max_bd'], r['earn'])
        st[r['day']] = s
    print('')
    print('=== 类型 × 情绪阶段（日等权，按各自卖点）===')
    R = evaluate(E[E['type'] != ''], st)
    print(R.to_string(index=False))
