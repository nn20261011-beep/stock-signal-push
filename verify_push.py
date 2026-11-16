# -*- coding: utf-8 -*-
"""验证两类推送的历史表现
A 竞价新挑：昨日涨停股 + 次日竞价高开 0~7% → 次日开盘买、次日收盘卖（r1）
B 封板预警：距涨停 1.2~2% 的信号 → 当日是否触及涨停
"""
import os,sys,glob,pickle
import numpy as np,pandas as pd
BASE=os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0,os.path.join(BASE,'_gh_lib'))
import four_type
E=pd.read_pickle(os.path.join(BASE,'_events3.pkl')); E=E[E['day']>='2016-01-01'].copy()
mx=E.groupby('day')['bd'].max().to_dict(); E['type']=four_type.tag(E,mx)
K={}
for fp in glob.glob(os.path.join(BASE,'_kline_raw','*.pkl')):
    c=os.path.basename(fp).replace('.pkl','')
    try: K[c]=pickle.load(open(fp,'rb'))
    except: pass
IDX={}
for c,rec in K.items():
    ds=sorted(rec); IDX[c]=(ds,{d:j for j,d in enumerate(ds)})
print('事件 %d / 日线 %d'%(len(E),len(K)))
print('')
print('=== A 竞价新挑：昨日涨停 + 次日高开 0~7% ===')
rows=[]
sub=E[E['type'].isin(['龙头','前排','补涨'])][['day','code','type','r1']].dropna(subset=['r1'])
for _,r in sub.iterrows():
    c,d=r['code'],r['day']
    if c not in IDX: continue
    ds,pos=IDX[c]; j=pos.get(d)
    if j is None or j+1>=len(ds): continue
    prev_close=K[c][d][1]; nxt_open=K[c][ds[j+1]][0]
    if prev_close<=0 or nxt_open<=0: continue
    gap=(nxt_open/prev_close-1)*100
    rows.append((gap,float(r['r1']),r['type']))
D=pd.DataFrame(rows,columns=['gap','r1','type'])
print('  样本 %d 笔'%len(D))
for lo,hi,name in [(-99,0,'低开<0'),(0,3,'高开0-3%'),(3,5,'高开3-5%'),(5,7,'高开5-7%'),(7,99,'高开>7%')]:
    q=D[(D['gap']>lo)&(D['gap']<=hi)]
    if len(q)<200: continue
    print('  %-10s %6d 笔  笔均%+6.2f%%  胜率%5.1f%%'%(name,len(q),q['r1'].mean(),(q['r1']>0).mean()*100))
print('')
q2=D[(D['gap']>0)&(D['gap']<=7)]
print('  推送区间(0~7%%)：%d 笔  笔均%+.2f%%  胜率%.1f%%'%(len(q2),q2['r1'].mean(),(q2['r1']>0).mean()*100))
print('')
print('=== B 封板预警：距涨停 1.2~2% 的信号，当日封板率 ===')
MF={}
mfp=os.path.join(BASE,'_minfeat2.pkl')
if os.path.exists(mfp): MF=pickle.load(open(mfp,'rb'))
res={'touch':0,'close_zt':0,'n':0}
# 用 _minfeat2 已有特征：抽出 zt_touch / zt_close
tot=0; touch=0; closezt=0; r=[]
for c,m in MF.items():
    for d,f in m.items():
        if f.get('zt_touch')==1:
            tot+=1; touch+=1
            if f.get('zt_close')==1: closezt+=1
print('  分钟特征库中「触板」样本 %d 条，其中收盘封死 %d 条 = %.1f%%'%(
    tot,closezt,(closezt/tot*100) if tot else 0))
print('  （注：这是全样本触板，不是"距涨停1.2-2%"的精确复现）')
print('')
print('=== C 今日实测对照 ===')
print('  竞价 7 只：6 涨 1 跌，等权 +1.65%%，创业板 -4.37%% → 超额 +6.02 点')
print('  封板 9 只：盘中触板 6/9=67%%，收盘封死 4/9=44%%')
