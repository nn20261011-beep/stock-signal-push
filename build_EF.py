# -*- coding: utf-8 -*-
"""E 卖法对比 + F 三段验证（基于 D 组有效特征）"""
import os
import numpy as np,pandas as pd
BASE=os.path.dirname(os.path.abspath(__file__))
OUT=os.path.join(BASE,'_dataset')
D=pd.read_parquet(os.path.join(OUT,'feat2.parquet'))
D['yr']=D['day'].str[:4].astype(int)

# 分位阈值（用全样本定，避免未来函数：实际应用滚动分位，这里先用固定分位近似）
q_vr=D['vr'].quantile(0.2); q_amp=D['amp'].quantile(0.2)
q_r5=D['r5'].quantile(0.8); q_gap=D['gap20'].quantile(0.8)
print('分位阈值：vr<=%.3f  amp<=%.3f%%  r5>=%.2f%%  gap20>=%.2f%%'%(q_vr,q_amp,q_r5,q_gap),flush=True)

def stat(s,label):
    if len(s)<50: 
        print('  %-34s 样本%d 不足'%(label,len(s))); return None
    return dict(label=label,n=len(s),days=s['day'].nunique(),
                op=s['t1_open'].mean(),opw=(s['t1_open']>0).mean()*100,
                hi=s['t1_high'].mean(),hiw=(s['t1_high']>0).mean()*100,
                cl=s['t1_close'].mean(),clw=(s['t1_close']>0).mean()*100,
                t2=s['t2_close'].mean())

print('')
print('=== 组合对比 ===')
print('%-34s %6s %5s %8s %6s %8s %6s %8s %6s %8s'%('组合','笔数','天','次开','胜率','次高','胜率','次收','胜率','T+2'))
combos=[
 ('全部涨停（基线）',D),
 ('vr低20%',D[D['vr']<=q_vr]),
 ('amp低20%',D[D['amp']<=q_amp]),
 ('vr低+amp低',D[(D['vr']<=q_vr)&(D['amp']<=q_amp)]),
 ('vr低+amp低+r5高',D[(D['vr']<=q_vr)&(D['amp']<=q_amp)&(D['r5']>=q_r5)]),
 ('vr低+amp低+gap高',D[(D['vr']<=q_vr)&(D['amp']<=q_amp)&(D['gap20']>=q_gap)]),
]
best=None
for lab,q in combos:
    r=stat(q,lab)
    if not r: continue
    print('%-34s %6d %5d %+7.2f%% %5.1f%% %+7.2f%% %5.1f%% %+7.2f%% %5.1f%% %+7.2f%%'%(
        lab,r['n'],r['days'],r['op'],r['opw'],r['hi'],r['hiw'],r['cl'],r['clw'],r['t2']))
    if lab!='全部涨停（基线）' and (best is None or r['op']>best[2]): best=(lab,q,r['op'])

print('')
print('=== E 组：最优组合的 4 种卖法 ===')
if best:
    lab,q,_bo=best
    print('  组合：%s（%d 笔 / %d 天）'%(lab,len(q),q['day'].nunique()))
    for k,cn in [('t1_open','次日开盘'),('t1_high','次日最高'),('t1_close','次日收盘'),('t2_close','T+2收盘')]:
        v=q[k].dropna()
        print('    %-8s 均值%+6.2f%%  胜率%5.1f%%  最大单笔%+6.2f%%  平均每笔天数%s'%(
            cn,v.mean(),(v>0).mean()*100,v.min(),'1' if k!='t2_close' else '2'))
    print('')
    print('=== F 组：三段验证（%s）==='%lab)
    segs=[(2016,2020,'第1段16-20'),(2021,2023,'第2段21-23'),(2024,2026,'第3段24-26')]
    ok=0
    for a,b,sn in segs:
        s=q[(q['yr']>=a)&(q['yr']<=b)]
        if len(s)<30: print('  %-12s 样本%d 不足'%(sn,len(s))); continue
        print('  %-12s %5d笔 %4d天  次开%+7.2f%%(胜%4.1f%%)  次高%+7.2f%%(胜%4.1f%%)  次收%+7.2f%%'%(
            sn,len(s),s['day'].nunique(),s['t1_open'].mean(),(s['t1_open']>0).mean()*100,
            s['t1_high'].mean(),(s['t1_high']>0).mean()*100,s['t1_close'].mean()))
        if s['t1_open'].mean()>0: ok+=1
    print('  三段中次日开盘为正：%d/3'%ok)
    print('')
    print('=== 逐日均值（最近20天）===')
    g=q.groupby('day').agg(n=('t1_open','size'),op=('t1_open','mean'),w=('t1_open',lambda x:(x>0).mean()*100)).tail(20)
    print(g.round(2).to_string())
    q.to_parquet(os.path.join(OUT,'final_rule.parquet'),index=False)
