# -*- coding: utf-8 -*-
"""只用 9:25 可知条件（昨日连板/昨日量比/昨日换手/今日高开）搜索最优规则"""
import pandas as pd,numpy as np
D=pd.read_pickle('_bt_auction_real.pkl').sort_values(['code','day']).reset_index(drop=True)
D['prev_vr']=D.groupby('code')['vr'].shift(1)
D['prev_tov']=D.groupby('code')['tov'].shift(1)
D['prev_p60']=D.groupby('code')['p60'].shift(1)
D['prev_chg']=D.groupby('code')['chg'].shift(1)
base=D[(D['prev_zt'])&(D['op_pct']>0)].copy()
print('昨日涨停样本 %d 笔'%len(base))
print('')
def st(q,minn=40):
    if len(q)<minn: return None
    return (len(q),q['day'].nunique(),q['r_op'].mean(),(q['r_op']>0).mean()*100,
            q['r_hi'].mean(),(q['r_hi']>0).mean()*100,q['r_cl'].mean(),(q['r_cl']>0).mean()*100)
def pr(lab,r):
    if not r: print('  %-40s 样本不足'%lab); return
    print('  %-40s %5d %4d %+7.2f%% %4.0f%% %+7.2f%% %4.0f%% %+7.2f%% %4.0f%%'%(
        lab,r[0],r[1],r[2],r[3],r[4],r[5],r[6],r[7]))
H='  %-40s %5s %4s %8s %5s %8s %5s %8s %5s'
print(H%('规则','笔数','天','次开','胜率','次高','胜率','次收','胜率'))
print('--- 1. 连板高度 × 高开上限 ---')
for bd in [1,2,3,4]:
    for lo,hi in [(0.5,4),(0,5),(2,5),(0.5,7)]:
        q=base[(base['prev_bd']==bd)&(base['op_pct']>lo)&(base['op_pct']<=hi)]
        pr('bd=%d + 高开%.1f-%.0f%%'%(bd,lo,hi),st(q))
print('')
print('--- 2. 在 bd>=3 上叠加昨日量比 ---')
b3=base[base['prev_bd']>=3]
for vmax in [1.0,1.5,2.0,99]:
    for lo,hi in [(0.5,4),(0,5),(2,5)]:
        q=b3[(b3['prev_vr']<=vmax)&(b3['op_pct']>lo)&(b3['op_pct']<=hi)]
        pr('bd>=3 + 昨vr<=%.1f + 高开%.1f-%.0f'%(vmax,lo,hi),st(q,30))
print('')
print('--- 3. 加昨日换手 ---')
for tmax in [5,10,20,99]:
    q=b3[(b3['prev_vr']<=1.5)&(b3['prev_tov']<tmax)&(b3['op_pct']>0.5)&(b3['op_pct']<=5)]
    pr('bd>=3 + 昨vr<=1.5 + 昨换手<%.0f + 高开0.5-5'%tmax,st(q,25))
print('')
print('--- 4. 加昨日位置 ---')
for pmin,pmax,lab in [(0,50,'昨p60<50'),(50,101,'昨p60>=50')]:
    q=b3[(b3['prev_vr']<=1.5)&(b3['prev_p60']>=pmin)&(b3['prev_p60']<pmax)&(b3['op_pct']>0.5)&(b3['op_pct']<=5)]
    pr('bd>=3 + 昨vr<=1.5 + '+lab+' + 高开0.5-5',st(q,20))
print('')
print('--- 5. 最终候选分段验证 ---')
CAND=b3[(b3['prev_vr']<=1.5)&(b3['op_pct']>0.5)&(b3['op_pct']<=5)]
print('  规则：昨日>=3板 + 昨日量比<=1.5 + 今日高开0.5~5%')
r=st(CAND,20)
pr('全部',r)
for a,b,lab in [('2024-11-06','2025-05-31','第1段24-11~25-05'),('2025-06-01','2025-12-31','第2段25-06~25-12'),
                ('2026-01-01','2026-06-30','第3段26-01~26-06'),('2026-07-01','2026-11-04','第4段26-07~26-11')]:
    q=CAND[(CAND['day']>=a)&(CAND['day']<=b)]
    if len(q)<3: print('    %s 样本%d'%(lab,len(q))); continue
    print('    %-20s %3d笔 次开%+7.2f%%(胜%3.0f%%) 次高%+7.2f%%(胜%3.0f%%)'%(
        lab,len(q),q['r_op'].mean(),(q['r_op']>0).mean()*100,q['r_hi'].mean(),(q['r_hi']>0).mean()*100))
print('')
print('--- 6. 逐笔明细 ---')
print('  %-11s %-8s %4s %7s %7s %8s %8s'%('日期','代码','板','昨vr','高开','次开','次高'))
for _,x in CAND.sort_values('day').iterrows():
    print('  %-11s %-8s %4d %7.2f %+6.2f%% %+7.2f%% %+7.2f%%'%(
        x['day'],x['code'],x['prev_bd'],x['prev_vr'],x['op_pct'],x['r_op'],x['r_hi']))
CAND.to_pickle('_final_rule.pkl')
