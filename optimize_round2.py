# -*- coding: utf-8 -*-
"""第二轮：邻域细化 + 滑点压力测试；目标=三段最差 Calmar（稳健优先）"""
import os,sys,json
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from bt_engine import Engine
BASE=os.path.dirname(os.path.abspath(__file__))
E=Engine()
SEGS=[('2016-01-01','2020-12-31'),('2021-01-01','2023-12-31'),('2024-01-01','2026-12-31')]
def robust(p):
    rs=[E.run(start=a,end=b,**p) for a,b in SEGS]
    return min(x['calmar'] for x in rs), rs
P0=dict(ret_col='sl5',theme_min=1,weight_cap=0.12,max_pos=10,exposure=0.40,
        streak_limit=2,halt_dd=-15.0,mode_stop=-3.0,zt_lo=25,zt_hi=60,
        earn_lo=-0.5,earn_hi=1.5,slippage=0.0)
print('=== 第二轮：邻域细化（目标=三段最差Calmar）===')
print('%-26s %8s %8s %8s %8s'%('参数','最差Calmar','年化均值','回撤均值','笔数均值'))
GRID=[('weight_cap',[0.10,0.12,0.15]),('max_pos',[8,10,12]),
      ('exposure',[0.30,0.40,0.50]),('streak_limit',[1,2,3]),
      ('theme_min',[1,2]),('zt',[(20,55),(22,58),(25,60)]),
      ('earn',[(-1.0,1.0),(-0.5,1.5),(-0.3,1.2)])]
best={}; rep=[]
for name,vals in GRID:
    rows=[]
    for v in vals:
        p=dict(P0)
        if name=='zt': p['zt_lo'],p['zt_hi']=v
        elif name=='earn': p['earn_lo'],p['earn_hi']=v
        else: p[name]=v
        mc,rs=robust(p)
        rows.append((v,mc,rs))
        print('  %-24s %8.2f %+7.1f%% %7.1f%% %7.0f'%(
            str(v),mc,sum(x['ann'] for x in rs)/3,sum(x['mdd'] for x in rs)/3,
            sum(x['trades'] for x in rs)/3))
    pick=max(rows,key=lambda x:x[1]); best[name]=pick[0]
    rep.append(dict(param=name,best=pick[0],robust=pick[1]))
    print('  → 最优 %s（三段最差Calmar %.2f）'%(pick[0],pick[1]))
    print('')
p2=dict(P0)
for k,v in best.items():
    if k=='zt': p2['zt_lo'],p2['zt_hi']=v
    elif k=='earn': p2['earn_lo'],p2['earn_hi']=v
    else: p2[k]=v
print('=== 第二轮组合 ===')
mc,rs=robust(p2)
print('  三段最差Calmar %.2f'%mc)
for (a,b),r in zip(SEGS,rs):
    print('    %s~%s 年化%+.1f%% 回撤%.1f%% Calmar%.2f 笔%d'%(a,b,r['ann'],r['mdd'],r['calmar'],r['trades']))
print('')
print('=== 滑点压力测试（全样本）===')
for sl in [0.0,0.2,0.5,1.0]:
    p=dict(p2); p['slippage']=sl
    r=E.run(**p)
    print('  滑点%.1f%%：年化%+7.1f%% 回撤%7.1f%% Calmar%5.2f 笔%5d 胜率%5.1f%%'%(
        sl,r['ann'],r['mdd'],r['calmar'],r['trades'],r['win']))
json.dump(dict(best={k:(list(v) if isinstance(v,tuple) else v) for k,v in best.items()},
               robust=mc,segs=rs),open(os.path.join(BASE,'_opt_round2.json'),'w',encoding='utf-8'),
          ensure_ascii=False,indent=1,default=str)
print('')
print('已存 _opt_round2.json')
