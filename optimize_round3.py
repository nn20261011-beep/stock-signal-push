# -*- coding: utf-8 -*-
"""第三轮：在 0.5% 现实成本下寻优，目标=三段最差 Calmar"""
import os,sys,json
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from bt_engine import Engine
BASE=os.path.dirname(os.path.abspath(__file__))
E=Engine()
SEGS=[('2016-01-01','2020-12-31'),('2021-01-01','2023-12-31'),('2024-01-01','2026-12-31')]
def robust(p):
    rs=[E.run(start=a,end=b,**p) for a,b in SEGS]
    return min(x['calmar'] for x in rs), rs
P=dict(ret_col='sl5',theme_min=1,weight_cap=0.12,max_pos=8,exposure=0.40,
       streak_limit=2,halt_dd=-15.0,mode_stop=-3.0,zt_lo=25,zt_hi=60,
       earn_lo=-0.5,earn_hi=1.5,slippage=0.5)
print('=== 第三轮（成本 0.5%%）起点 ===')
mc,rs=robust(P)
print('  三段最差 Calmar %.2f'%mc)
for (a,b),r in zip(SEGS,rs):
    print('    %s 年化%+.1f%% 回撤%.1f%% Calmar%.2f 笔%d'%(a,r['ann'],r['mdd'],r['calmar'],r['trades']))
print('')
print('%-30s %8s %9s %9s'%('调整','最差Calmar','年化均值','回撤均值'))
GRID=[('exposure',[0.3,0.4,0.5]),('max_pos',[6,8,10]),
      ('weight_cap',[0.10,0.12,0.15]),('streak_limit',[1,2,3]),
      ('ret_col',['sl5','rbreak','r1']),('theme_min',[1,2])]
best={}
for name,vals in GRID:
    rows=[]
    for v in vals:
        p=dict(P); p[name]=v
        mc,rs=robust(p)
        rows.append((v,mc,rs))
        print('  %-28s %8.2f %+8.1f%% %8.1f%%'%(
            '%s=%s'%(name,v),mc,sum(x['ann'] for x in rs)/3,sum(x['mdd'] for x in rs)/3))
    pick=max(rows,key=lambda x:x[1]); best[name]=pick[0]
    P[name]=pick[0]
    print('  → 采用 %s（%.2f）'%(pick[0],pick[1]))
    print('')
mc,rs=robust(P)
print('=== 第三轮最终 ===')
print('  三段最差 Calmar %.2f'%mc)
for (a,b),r in zip(SEGS,rs):
    print('    %s~%s 年化%+.1f%% 回撤%.1f%% Calmar%.2f 笔%d 胜率%.1f%%'%(
        a,b,r['ann'],r['mdd'],r['calmar'],r['trades'],r['win']))
full=E.run(start='2016-01-01',end='2026-12-31',**P)
print('  全样本：年化%+.1f%% 回撤%.1f%% Calmar%.2f 笔%d 胜率%.1f%%'%(
    full['ann'],full['mdd'],full['calmar'],full['trades'],full['win']))
P['_meta']=dict(round3_robust=mc,segments=[dict(seg='%s~%s'%(a,b),**r) for (a,b),r in zip(SEGS,rs)],
                full=full,trained_on='2016-2026 事件池 30287 行',cost='0.5% 单边')
json.dump(P,open(os.path.join(BASE,'_opt_final.json'),'w',encoding='utf-8'),
          ensure_ascii=False,indent=1,default=str)
print('')
print('已存 _opt_final.json')
