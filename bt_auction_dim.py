# -*- coding: utf-8 -*-
"""竞价新挑三维度验证：梯队断层 / 题材共振 / 位置分位
口径：昨日涨停 + 次日竞价高开 0~7% → 开盘买、当日收盘卖（r1）
"""
import os,sys,glob,pickle,json
import numpy as np,pandas as pd
from collections import defaultdict
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
# 每日连板结构：首板数 / 2板以上数
bd_by_day=defaultdict(dict)
for _,r in E.iterrows():
    if r['bd']>=1: bd_by_day[r['day']][r['code']]=int(r['bd'])
ladder={}
for d,m in bd_by_day.items():
    first=sum(1 for v in m.values() if v==1)
    high=sum(1 for v in m.values() if v>=2)
    ladder[d]=(first,high,high/max(first,1))
# 题材映射
CJ=json.load(open(os.path.join(BASE,'_gh_lib','_concept.json'),encoding='utf-8'))
EXCL=['参股','专精特新','融资融券','股权激励','业绩预','重组','重仓','解禁','分拆','国企改革','资产注入','整体上市','ST','摘帽','送转','未股改','三板','超大盘','含H股','含B股','含GDR','外资背景','高校背景','股期','科创50','央企50','社保','基金','券商','信托','保险','本地','成渝','黄河三角','海峡西岸','陕甘宁','长株潭','皖江','雄安','京津冀','海南自贸','武汉规划','沿海发展','前海','图们江','自贸','振兴沈阳','海上丝路','三沙','水域改革','朝鲜改革','迪士尼','本月','沪股通','深股通','MSCI','标普','富时','转融券','融资']
code2con=defaultdict(list)
for node,codes in CJ['concepts'].items():
    nm=CJ.get('names',{}).get(node,node)
    if any(x in nm for x in EXCL): continue
    for c in codes: code2con[c].append(nm)
# 每日题材涨停数
con_zt=defaultdict(lambda: defaultdict(int))
for d,m in bd_by_day.items():
    for c in m:
        for t in code2con.get(c,[]): con_zt[d][t]+=1

rows=[]
sub=E[E['type'].isin(['龙头','前排','补涨'])][['day','code','type','r1','bd','p60']].dropna(subset=['r1'])
cnt=0
for _,r in sub.iterrows():
    c,d=r['code'],r['day']
    if c not in IDX: continue
    ds,pos=IDX[c]; j=pos.get(d)
    if j is None or j+1>=len(ds): continue
    pc=K[c][d][1]; no=K[c][ds[j+1]][0]
    if pc<=0 or no<=0: continue
    gap=(no/pc-1)*100
    if not (0<gap<=7): continue
    l=ladder.get(d,(0,0,0))
    cons=code2con.get(c,[])
    czt=max([con_zt[d].get(t,0) for t in cons],default=0)
    rows.append(dict(day=d,code=c,type=r['type'],gap=gap,r1=float(r['r1']),
                     bd=int(r['bd']),p60=float(r['p60']),
                     ratio=l[2],czt=czt,ncon=len(cons)))
    cnt+=1
D=pd.DataFrame(rows)
print('竞价新挑样本 %d 笔'%len(D))
print('基准：笔均%+.2f%% 胜率%.1f%%'%(D['r1'].mean(),(D['r1']>0).mean()*100))
print('')
print('=== 维度1 梯队比值（当日2板以上/首板）===')
D['seg_l']=pd.cut(D['ratio'],[-1,0.2,0.4,0.8,99],labels=['<0.2 断层','0.2-0.4','0.4-0.8','>0.8 健康'])
for s,g in D.groupby('seg_l',observed=True):
    if len(g)<200: continue
    print('  %-12s %5d 笔  笔均%+7.2f%%  胜率%5.1f%%'%(s,len(g),g['r1'].mean(),(g['r1']>0).mean()*100))
print('')
print('=== 维度2 题材共振（同题材当日涨停数）===')
D['seg_c']=pd.cut(D['czt'],[-1,0,1,2,4,99],labels=['0 无题材','1','2','3-4','>=5'])
for s,g in D.groupby('seg_c',observed=True):
    if len(g)<100: continue
    print('  %-10s %5d 笔  笔均%+7.2f%%  胜率%5.1f%%'%(s,len(g),g['r1'].mean(),(g['r1']>0).mean()*100))
print('')
print('=== 维度3 位置分位 p60 ===')
D['seg_p']=pd.cut(D['p60'],[-1,40,60,80,100],labels=['<40 低位','40-60','60-80','>80 高位'])
for s,g in D.groupby('seg_p',observed=True):
    if len(g)<200: continue
    print('  %-10s %5d 笔  笔均%+7.2f%%  胜率%5.1f%%'%(s,len(g),g['r1'].mean(),(g['r1']>0).mean()*100))
print('')
print('=== 三维叠加 ===')
q=D[(D['ratio']>=0.4)&(D['czt']>=2)&(D['p60']<60)]
print('  梯队>=0.4 + 题材>=2 + 位置<60：%d 笔  笔均%+.2f%% 胜率%.1f%%'%(
    len(q),q['r1'].mean(),(q['r1']>0).mean()*100))
q2=D[(D['ratio']<0.2)&(D['czt']==0)&(D['p60']>80)]
print('  反例：断层 + 无题材 + 高位：%d 笔  笔均%+.2f%% 胜率%.1f%%'%(
    len(q2),q2['r1'].mean(),(q2['r1']>0).mean()*100))
D.to_pickle(os.path.join(BASE,'_auction_dim.pkl'))
print('')
print('明细已存 _auction_dim.pkl')
