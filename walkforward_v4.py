# -*- coding: utf-8 -*-
"""走查验证：同一套参数在三段独立区间跑，看是否都成立"""
import os,sys,json
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from bt_engine import Engine
BASE=os.path.dirname(os.path.abspath(__file__))
E=Engine()
BASE_P=dict(ret_col='sl5',theme_min=2,weight_cap=0.10,max_pos=8,exposure=0.80,
            streak_limit=3,halt_dd=-20.0,mode_stop=-3.0,zt_lo=20,zt_hi=55,
            earn_lo=-1.0,earn_hi=1.0)
OPT_P=dict(ret_col='sl5',theme_min=1,weight_cap=0.12,max_pos=10,exposure=0.40,
           streak_limit=2,halt_dd=-15.0,mode_stop=-3.0,zt_lo=25,zt_hi=60,
           earn_lo=-0.5,earn_hi=1.5)
SEGS=[('2016-01-01','2020-12-31','第1段 16-20'),
      ('2021-01-01','2023-12-31','第2段 21-23'),
      ('2024-01-01','2026-12-31','第3段 24-26')]
print('%-14s %-8s %8s %8s %8s %7s'%('区间','参数','年化','回撤','Calmar','笔数'))
res={}
for st,en,name in SEGS:
    for tag,p in [('基准',BASE_P),('优化',OPT_P)]:
        r=E.run(start=st,end=en,**p)
        print('%-14s %-8s %+7.1f%% %7.1f%% %7.2f %7d'%(
            name,tag,r['ann'],r['mdd'],r['calmar'],r['trades']))
        res.setdefault(name,{})[tag]=r
    print('')
json.dump(res,open(os.path.join(BASE,'_walkforward.json'),'w',encoding='utf-8'),
          ensure_ascii=False,indent=1)
print('三段对比完成，已存 _walkforward.json')
