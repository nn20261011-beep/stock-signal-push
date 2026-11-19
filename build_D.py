# -*- coding: utf-8 -*-
"""D 组：单特征分档验证 + 有效特征筛选 + 组合"""
import os
import numpy as np,pandas as pd
BASE=os.path.dirname(os.path.abspath(__file__))
OUT=os.path.join(BASE,'_dataset')
D=pd.read_parquet(os.path.join(OUT,'feat.parquet'))
print('样本 %d 条 / %d 天'%(len(D),D['day'].nunique()),flush=True)
print('基线：t1_open %+.2f%% (胜%.1f%%)  t1_high %+.2f%% (胜%.1f%%)  t1_close %+.2f%% (胜%.1f%%)'%(
    D['t1_open'].mean(),(D['t1_open']>0).mean()*100,
    D['t1_high'].mean(),(D['t1_high']>0).mean()*100,
    D['t1_close'].mean(),(D['t1_close']>0).mean()*100))
print('')
FEATS=['r5','r10','r20','amp','vr','gap20','p60','theme_zt','lhb','chg']
print('=== D1/D2 单特征 5 档（看 t1_open）===')
print('%-9s %-6s %7s %9s %8s %9s %8s'%('特征','档','笔数','次开均值','胜率','次高均值','次高胜率'))
valid=[]
for f in FEATS:
    s=D[f].dropna()
    if len(s)<1000: continue
    try:
        D['_b']=pd.qcut(D[f],5,labels=False,duplicates='drop')
    except Exception:
        continue
    g=D.dropna(subset=[f]).groupby('_b').agg(
        n=('t1_open','size'),op=('t1_open','mean'),opw=('t1_open',lambda x:(x>0).mean()*100),
        hi=('t1_high','mean'),hiw=('t1_high',lambda x:(x>0).mean()*100))
    if len(g)<5: continue
    lo,hi_=g['op'].iloc[0],g['op'].iloc[-1]
    diff=abs(hi_-lo)
    mono=sum(1 for i in range(4) if (g['op'].iloc[i+1]-g['op'].iloc[i])*(hi_-lo)>0)
    for b,r in g.iterrows():
        print('%-9s %-6d %7d %+8.2f%% %7.1f%% %+8.2f%% %7.1f%%'%(f,b,r['n'],r['op'],r['opw'],r['hi'],r['hiw']))
    tag='✅有效' if diff>=1.0 and mono>=3 else ('△弱' if diff>=0.5 else '')
    print('  → 极差 %.2f 点  单调 %d/4  %s'%(diff,mono,tag))
    if diff>=1.0 and mono>=3: valid.append((f,diff,mono,g['op'].idxmax()))
    print('')
print('=== 有效特征 %d 个 ==='%len(valid))
for f,d,m,b in valid: print('  %-9s 极差%.2f 单调%d/4 最优档%d'%(f,d,m,b))
D.to_parquet(os.path.join(OUT,'feat2.parquet'),index=False)
