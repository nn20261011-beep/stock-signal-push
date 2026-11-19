# -*- coding: utf-8 -*-
"""B+C+D+E+F 一体化：特征 → 环境分档 → 选股验证 → 卖法对比 → 三段验证"""
import os,glob,pickle,json
import numpy as np,pandas as pd
BASE=os.path.dirname(os.path.abspath(__file__))
OUT=os.path.join(BASE,'_dataset')

print('[B1] 建样本与特征',flush=True)
ZT=pd.read_parquet(os.path.join(OUT,'zt_daily.parquet'))
ZT=ZT[ZT['day']>='2016-01-01'].copy()
print('  涨停记录 %d 条'%len(ZT),flush=True)

K={}
for fp in glob.glob(os.path.join(BASE,'_kline_raw','*.pkl')):
    c=os.path.basename(fp).replace('.pkl','')
    try: K[c]=pickle.load(open(fp,'rb'))
    except: pass
print('  日线 %d 只'%len(K),flush=True)

# 题材
TH=pd.read_parquet(os.path.join(OUT,'theme_daily.parquet'))
CJ=json.load(open(os.path.join(BASE,'_gh_lib','_concept.json'),encoding='utf-8'))
EXCL=['参股','专精特新','融资融券','股权激励','业绩预','重组','重仓','解禁','分拆','国企改革',
      '资产注入','整体上市','ST','摘帽','送转','未股改','三板','超大盘','含H股','含B股','含GDR',
      '外资背景','高校背景','股期','科创50','央企50','社保','基金','券商','信托','保险','本地',
      '成渝','黄河三角','海峡西岸','陕甘宁','长株潭','皖江','雄安','京津冀','海南自贸','武汉规划',
      '沿海发展','前海','图们江','自贸','振兴沈阳','海上丝路','三沙','水域改革','朝鲜改革',
      '迪士尼','本月','沪股通','深股通','MSCI','标普','富时','转融券','融资']
from collections import defaultdict
code2con=defaultdict(list)
for node,codes in CJ['concepts'].items():
    nm=CJ.get('names',{}).get(node,node)
    if any(x in nm for x in EXCL): continue
    for c in codes: code2con[c].append(nm)
thmap={(r['day'],r['theme']):(r['zt_count'],r['rank']) for _,r in TH.iterrows()}

# 龙虎榜
LHB=pd.read_parquet(os.path.join(OUT,'lhb.parquet'))
LHB['day']=LHB['上榜日'].astype(str).str[:10]
lhmap={}
for _,r in LHB.iterrows():
    lhmap[(str(r['代码']).zfill(6),r['day'])]=r.get('龙虎榜净买额',0)

rows=[]
miss=0
for i,(code,day) in enumerate(zip(ZT['code'],ZT['day'])):
    rec=K.get(code)
    if not rec: miss+=1; continue
    ds=sorted(rec)
    if day not in ds: miss+=1; continue
    j=ds.index(day)
    if j<25 or j+2>=len(ds): continue
    C=[rec[d][1] for d in ds]; H=[rec[d][2] for d in ds]; L=[rec[d][3] for d in ds]; V=[rec[d][4] for d in ds]
    ma20=sum(C[j-19:j+1])/20
    v5=sum(V[j-4:j+1])/5; v20=sum(V[j-19:j+1])/20
    cons=code2con.get(code,[])
    tz,tr=0,99
    for t in cons:
        v=thmap.get((day,t))
        if v and v[0]>tz: tz,tr=v[0],v[1]
    nx=ds[j+1]; n2=ds[j+2] if j+2<len(ds) else None
    rows.append(dict(code=code,day=day,
        r5=(C[j]/C[j-6]-1)*100 if j>=6 else np.nan,
        r10=(C[j]/C[j-11]-1)*100 if j>=11 else np.nan,
        r20=(C[j]/C[j-21]-1)*100 if j>=21 else np.nan,
        amp=(H[j]-L[j])/C[j-1]*100,
        vr=V[j]/v20 if v20>0 else np.nan,
        gap20=(C[j]/ma20-1)*100,
        p60=sum(1 for x in C[j-59:j+1] if x<C[j])/min(60,j+1)*100,
        theme_zt=tz,theme_rank=tr,
        lhb=lhmap.get((code,day),0),
        chg=(C[j]/C[j-1]-1)*100,
        # 标签
        t1_open=(rec[nx][0]/C[j]-1)*100,
        t1_high=(rec[nx][2]/C[j]-1)*100,
        t1_close=(rec[nx][1]/C[j]-1)*100,
        t2_close=(rec[n2][1]/C[j]-1)*100 if n2 else np.nan,
    ))
D=pd.DataFrame(rows)
print('  有效样本 %d 条（缺日线 %d）'%(len(D),miss),flush=True)
D.to_parquet(os.path.join(OUT,'feat.parquet'),index=False)

print('')
print('=== B 组：特征与次日收益的原始分布 ===')
for c in ['r5','r10','r20','amp','vr','gap20','p60','theme_zt','lhb']:
    v=D[c].dropna()
    print('  %-9s 中位%8.2f  P10%8.2f  P90%8.2f  非空%d'%(c,v.median(),v.quantile(.1),v.quantile(.9),len(v)))
print('')
print('=== 标签基线 ===')
for c in ['t1_open','t1_high','t1_close','t2_close']:
    v=D[c].dropna()
    print('  %-9s 均值%+6.2f%%  胜率%4.1f%%  n=%d'%(c,v.mean(),(v>0).mean()*100,len(v)))
