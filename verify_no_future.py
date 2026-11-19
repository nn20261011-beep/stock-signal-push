# -*- coding: utf-8 -*-
"""检查未来函数：把 vr 换成「昨日量比」（9:25可知），看策略是否还成立"""
import pandas as pd,numpy as np
D=pd.read_pickle('_bt_auction_real.pkl')
D=D.sort_values(['code','day']).reset_index(drop=True)
# 昨日量比（T-1日全天量比，9:25时已知）
D['prev_vr']=D.groupby('code')['vr'].shift(1)
D['prev_tov']=D.groupby('code')['tov'].shift(1)
base=D[(D['prev_zt'])&(D['op_pct']>0)&(D['op_pct']<=7)].copy()
print('基础样本 %d 笔'%len(base))
print('')
def st(q):
    if len(q)<20: return None
    return (len(q),q['day'].nunique(),q['r_op'].mean(),(q['r_op']>0).mean()*100,
            q['r_hi'].mean(),(q['r_hi']>0).mean()*100,q['r_cl'].mean(),(q['r_cl']>0).mean()*100)
def pr(lab,r):
    if not r: print('%-34s 样本不足'%lab); return
    print('%-34s %5d %4d %+8.2f%% %5.0f%% %+8.2f%% %5.0f%% %+8.2f%% %5.0f%%'%(
        lab,r[0],r[1],r[2],r[3],r[4],r[5],r[6],r[7]))
print('%-34s %5s %4s %9s %6s %9s %6s %9s %6s'%('条件','笔数','天','次开','胜率','次高','胜率','次收','胜率'))
print('--- A. 用「当日全天量比」（未来函数，不可执行）---')
pr('3板 + 当日vr<=1.5',st(base[(base['prev_bd']==3)&(base['vr']<=1.5)]))
print('--- B. 用「昨日量比」（9:25可执行）---')
for lo,hi,lab in [(0,1.5,'3板 + 昨日vr<=1.5'),(1.5,99,'3板 + 昨日vr>1.5')]:
    pr(lab,st(base[(base['prev_bd']==3)&(base['prev_vr']>lo)&(base['prev_vr']<=hi)]))
print('')
print('--- C. 3板 纯规则（只看连板，不用量能）---')
pr('3板 全部',st(base[base['prev_bd']==3]))
print('')
print('--- D. 3板 + 高开区间（9:25可知）---')
for lo,hi,lab in [(0,2,'3板 + 高开0-2%'),(2,4,'3板 + 高开2-4%'),(4,7,'3板 + 高开4-7%')]:
    pr(lab,st(base[(base['prev_bd']==3)&(base['op_pct']>lo)&(base['op_pct']<=hi)]))
print('')
print('--- E. 3板 + 昨日换手<8（9:25可知）---')
pr('3板 + 昨日tov<8',st(base[(base['prev_bd']==3)&(base['prev_tov']<8)]))
pr('3板 + 昨日tov>=8',st(base[(base['prev_bd']==3)&(base['prev_tov']>=8)]))
print('')
print('--- F. 可用条件组合 ---')
c1=base[(base['prev_bd']==3)&(base['prev_tov']<8)]
pr('3板 + 昨日tov<8 + 高开0-4',st(c1[c1['op_pct']<=4]))
c2=base[(base['prev_bd']==3)&(base['prev_vr']<=1.5)&(base['op_pct']<=4)]
pr('3板 + 昨日vr<=1.5 + 高开0-4',st(c2))
print('')
print('--- G. 分段验证：3板 + 昨日tov<8 ---')
cand=base[(base['prev_bd']==3)&(base['prev_tov']<8)]
for a,b,lab in [('2024-11-06','2025-05-31','第1段'),('2025-06-01','2025-12-31','第2段'),
                ('2026-01-01','2026-06-30','第3段'),('2026-07-01','2026-11-04','第4段')]:
    q=cand[(cand['day']>=a)&(cand['day']<=b)]
    if len(q)<3: print('  %s 样本%d 不足'%(lab,len(q))); continue
    print('  %s %3d笔 %+7.2f%%(胜%3.0f%%) 次高%+7.2f%%(胜%3.0f%%)'%(
        lab,len(q),q['r_op'].mean(),(q['r_op']>0).mean()*100,q['r_hi'].mean(),(q['r_hi']>0).mean()*100))
