# -*- coding: utf-8 -*-
"""可执行性检查：最优组合里有多少是一字板（开盘即涨停，买不到）"""
import os,glob,pickle
import numpy as np,pandas as pd
BASE=os.path.dirname(os.path.abspath(__file__))
OUT=os.path.join(BASE,'_dataset')
Q=pd.read_parquet(os.path.join(OUT,'final_rule.parquet'))
print('最优组合 %d 笔'%len(Q),flush=True)

K={}
for fp in glob.glob(os.path.join(BASE,'_kline_raw','*.pkl')):
    c=os.path.basename(fp).replace('.pkl','')
    try: K[c]=pickle.load(open(fp,'rb'))
    except: pass

rows=[]
for code,day in zip(Q['code'],Q['day']):
    rec=K.get(code)
    if not rec: continue
    ds=sorted(rec)
    if day not in ds: continue
    j=ds.index(day)
    if j==0: continue
    prev=rec[ds[j-1]][1]; o=rec[ds[j]][0]; c=rec[ds[j]][1]; h=rec[ds[j]][2]; l=rec[ds[j]][3]
    lim=20.0 if code.startswith(('30','68')) else 10.0
    limit_up=round(prev*(1+lim/100),2)
    yizi = o>=limit_up*0.999            # 开盘即涨停 = 一字板，买不到
    rows.append(dict(code=code,day=day,yizi=yizi,
                     open_gap=(o/prev-1)*100,
                     intraday_low_gap=(l/prev-1)*100))
E=pd.DataFrame(rows)
print('可判定 %d 笔'%len(E),flush=True)
print('')
print('=== 可执行性 ===')
print('  一字板（开盘即涨停，买不到）：%d 笔 = %.1f%%'%(E['yizi'].sum(),E['yizi'].mean()*100))
print('  非一字板（可买入）：%d 笔 = %.1f%%'%((~E['yizi']).sum(),(~E['yizi']).mean()*100))
print('')
print('=== 开盘涨幅分布 ===')
print(E['open_gap'].describe().round(2).to_string())
print('')
print('=== 分档：开盘涨幅 vs 占比 ===')
E['gap_bin']=pd.cut(E['open_gap'],[-99,0,2,5,8,9.5,99],
                    labels=['低开<0','0-2%','2-5%','5-8%','8-9.5%','接近涨停'])
print(E.groupby('gap_bin',observed=True).agg(n=('yizi','size'),yizi_pct=('yizi','mean')).assign(
    yizi_pct=lambda x:(x['yizi_pct']*100).round(1)).to_string())
print('')
# 排除一字板后的真实收益
Q2=Q.merge(E[['code','day','yizi','open_gap']],on=['code','day'],how='left')
buyable=Q2[Q2['yizi']==False]
print('=== 排除一字板后（真正能买到的）===')
if len(buyable)>50:
    print('  %d 笔 / %d 天'%(len(buyable),buyable['day'].nunique()))
    for k,cn in [('t1_open','次日开盘'),('t1_high','次日最高'),('t1_close','次日收盘')]:
        v=buyable[k].dropna()
        print('    %-8s 均值%+6.2f%%  胜率%5.1f%%'%(cn,v.mean(),(v>0).mean()*100))
    print('')
    print('  分段：')
    buyable=buyable.copy(); buyable['yr']=buyable['day'].str[:4].astype(int)
    for a,b,sn in [(2016,2020,'16-20'),(2021,2023,'21-23'),(2024,2026,'24-26')]:
        s=buyable[(buyable['yr']>=a)&(buyable['yr']<=b)]
        if len(s)<30: continue
        print('    %s %4d笔 次开%+6.2f%%(胜%4.1f%%)'%(sn,len(s),s['t1_open'].mean(),(s['t1_open']>0).mean()*100))
else:
    print('  可买入样本 %d 笔，不足'%len(buyable))
Q2.to_parquet(os.path.join(OUT,'final_rule_checked.parquet'),index=False)
