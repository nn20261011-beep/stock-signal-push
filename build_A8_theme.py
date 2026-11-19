# -*- coding: utf-8 -*-
"""A8 题材每日涨停数：本地日线涨停记录 × _concept.json 映射 → 每日每题材涨停数及排名"""
import os,json,pickle,glob
import pandas as pd
from collections import defaultdict
BASE=os.path.dirname(os.path.abspath(__file__))
OUT=os.path.join(BASE,'_dataset')
ZT=pd.read_parquet(os.path.join(OUT,'zt_daily.parquet'))
ZT['c6']=ZT['code'].str[-6:]
print('涨停记录 %d 条 / %d 天'%(len(ZT),ZT['day'].nunique()),flush=True)

CJ=json.load(open(os.path.join(BASE,'_gh_lib','_concept.json'),encoding='utf-8'))
EXCL=['参股','专精特新','融资融券','股权激励','业绩预','重组','重仓','解禁','分拆','国企改革',
      '资产注入','整体上市','ST','摘帽','送转','未股改','三板','超大盘','含H股','含B股','含GDR',
      '外资背景','高校背景','股期','科创50','央企50','社保','基金','券商','信托','保险','本地',
      '成渝','黄河三角','海峡西岸','陕甘宁','长株潭','皖江','雄安','京津冀','海南自贸','武汉规划',
      '沿海发展','前海','图们江','自贸','振兴沈阳','海上丝路','三沙','水域改革','朝鲜改革',
      '迪士尼','本月','沪股通','深股通','MSCI','标普','富时','转融券','融资']
code2con=defaultdict(list)
ncon=0
for node,codes in CJ['concepts'].items():
    nm=CJ.get('names',{}).get(node,node)
    if any(x in nm for x in EXCL): continue
    ncon+=1
    for c in codes: code2con[c].append(nm)
print('有效题材 %d 个 / 覆盖 %d 只票'%(ncon,len(code2con)),flush=True)

# 每日每题材涨停数
cnt=defaultdict(lambda: defaultdict(int))
for _,r in ZT.iterrows():
    for t in code2con.get(r['c6'],[]):
        cnt[r['day']][t]+=1
rows=[]
for d,m in cnt.items():
    total=sum(1 for _ in m)
    # 按涨停数降序排名
    ordered=sorted(m.items(),key=lambda x:(-x[1],x[0]))
    for rank,(t,n) in enumerate(ordered,1):
        rows.append(dict(day=d,theme=t,zt_count=n,rank=rank,themes_total=total))
D=pd.DataFrame(rows)
D.to_parquet(os.path.join(OUT,'theme_daily.parquet'),index=False)
print('')
print('完成：%d 行 / %d 天 / %d 题材'%(len(D),D['day'].nunique(),D['theme'].nunique()),flush=True)
print('日均题材数 %.1f，单题材日均涨停 %.2f'%(D.groupby('day').size().mean(),D['zt_count'].mean()),flush=True)
print('存 _dataset/theme_daily.parquet',flush=True)
print('')
print('样例（2026-11-19 TOP5）:')
q=D[D['day']=='2026-11-19'].sort_values('rank').head(5)
print(q.to_string(index=False) if len(q) else '  当日无数据')
