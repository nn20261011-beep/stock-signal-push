# -*- coding: utf-8 -*-
"""第一轮：单参数扫描 → 找每个参数的最优方向"""
import os,sys,json,time
import numpy as np
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from bt_engine import Engine
BASE=os.path.dirname(os.path.abspath(__file__))
E=Engine()
BASE_PARAMS=dict(ret_col='sl5',theme_min=2,weight_cap=0.10,max_pos=8,exposure=0.80,
                 streak_limit=3,halt_dd=-20.0,mode_stop=-3.0,
                 zt_lo=20,zt_hi=55,earn_lo=-1.0,earn_hi=1.0)
base=E.run(**BASE_PARAMS)
print('')
print('基准：年化%+.1f%% 回撤%.1f%% Calmar%.2f 笔%d 胜率%.1f%%'%(
    base['ann'],base['mdd'],base['calmar'],base['trades'],base['win']))
print('')
GRID=[
 ('ret_col',['r1','rbreak','sl5','r10']),
 ('theme_min',[1,2,3,5]),
 ('weight_cap',[0.05,0.08,0.10,0.12]),
 ('max_pos',[4,6,8,10]),
 ('exposure',[0.4,0.6,0.8,1.0]),
 ('streak_limit',[2,3,4,99]),
 ('halt_dd',[-10.0,-15.0,-20.0,-30.0]),
 ('mode_stop',[-2.0,-3.0,-5.0,-99.0]),
 ('zt',[(15,45),(20,55),(25,60),(30,70)]),
 ('earn',[(-2.0,2.0),(-1.0,1.0),(-0.5,1.5),(0.0,3.0)]),
]
best={}
report=[]
t0=time.time()
for name,vals in GRID:
    print('=== %s ==='%name,flush=True)
    rows=[]
    for v in vals:
        p=dict(BASE_PARAMS)
        if name=='zt': p['zt_lo'],p['zt_hi']=v
        elif name=='earn': p['earn_lo'],p['earn_hi']=v
        else: p[name]=v
        r=E.run(**p)
        rows.append((v,r))
        print('  %-22s 年化%+7.1f%% 回撤%7.1f%% Calmar%5.2f 笔%5d 胜率%5.1f%%'%(
            str(v),r['ann'],r['mdd'],r['calmar'],r['trades'],r['win']),flush=True)
    ok=[x for x in rows if x[0] in ([99,99.0] and [99] or [x[0]])]
    pick=max(rows,key=lambda x:x[1]['calmar'])
    best[name]=pick[0]
    report.append(dict(param=name,best=pick[0],
                       best_calmar=round(pick[1]['calmar'],3),
                       all=[dict(v=str(v),ann=round(r['ann'],2),mdd=round(r['mdd'],2),
                                 calmar=round(r['calmar'],3),trades=r['trades'],win=round(r['win'],1))
                            for v,r in rows]))
    print('  → 最优 %s（Calmar %.2f）'%(pick[0],pick[1]['calmar']),flush=True)
    print('',flush=True)
print('单参数最优组合:')
print(json.dumps({k:str(v) for k,v in best.items()},ensure_ascii=False))
# 组合回测
p2=dict(BASE_PARAMS)
for k,v in best.items():
    if k=='zt': p2['zt_lo'],p2['zt_hi']=v
    elif k=='earn': p2['earn_lo'],p2['earn_hi']=v
    else: p2[k]=v
r2=E.run(**p2)
print('')
print('=== 组合结果 ===')
print('  年化%+.1f%% 回撤%.1f%% Calmar%.2f 笔%d 胜率%.1f%%'%(
    r2['ann'],r2['mdd'],r2['calmar'],r2['trades'],r2['win']))
json.dump(dict(base=base,grid=report,best_params={k:(list(v) if isinstance(v,tuple) else v) for k,v in best.items()},
               combo=r2),open(os.path.join(BASE,'_opt_round1.json'),'w',encoding='utf-8'),
          ensure_ascii=False,indent=1,default=str)
print('')
print('用时 %.0f 分钟，已存 _opt_round1.json'%((time.time()-t0)/60))
