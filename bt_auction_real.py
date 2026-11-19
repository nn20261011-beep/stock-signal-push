# -*- coding: utf-8 -*-
"""竞价战法逐日回测（真实历史，不是27笔）
样本表 _intraday_daily：2024-11-06~2026-11-04，2661只，含次日 n_open/n_close/n_high
口径：T日竞价(开盘)买入 → T+1开盘/最高/收盘三种卖法
"""
import pickle,pandas as pd,numpy as np
BASE='.'
D=pickle.load(open(BASE+'/_intraday_daily.pkl','rb'))
D['day']=D['day'].astype(str)
D=D.sort_values(['code','day']).reset_index(drop=True)
# 昨日是否涨停
D['prev_zt']=D.groupby('code')['is_zt'].shift(1).fillna(False).astype(bool)
# 连板数（截至前一日）
def streak(g):
    z=g['is_zt'].values; out=np.zeros(len(z),dtype=int); c=0
    for i in range(len(z)):
        out[i]=c
        c=c+1 if z[i] else 0
    return pd.Series(out,index=g.index)
D['prev_bd']=D.groupby('code',group_keys=False).apply(streak)
# 买入价 = 当日开盘
D['buy']=D['pc']*(1+D['op_pct']/100)
D['buy']=D['buy'].where(D['buy']>0)
# 三种卖点收益
for k,col in [('r_op','n_open'),('r_hi','n_high'),('r_cl','n_close')]:
    D[k]=(D[col]/D['buy']-1)*100
# 次日一字跌停（卖不出）：次日开=高=收 且 <= 昨收*0.9
D['t1_limit_down']=(D['n_open']<=D['close']*0.901)&(D['n_high']<=D['close']*0.901)
D['t1_limit_up']=(D['n_open']>=D['close']*1.099)

full=D[D['r_cl'].notna()].copy()
print('全表 %d 行 / %d 天 / %d 只'%(len(full),full['day'].nunique(),full['code'].nunique()))
print('')

def stat(s,label):
    if len(s)<30: return None
    days=s['day'].nunique()
    return dict(label=label,n=len(s),days=days,
                op_mean=s['r_op'].mean(),op_win=(s['r_op']>0).mean()*100,
                hi_mean=s['r_hi'].mean(),hi_win=(s['r_hi']>0).mean()*100,
                cl_mean=s['r_cl'].mean(),cl_win=(s['r_cl']>0).mean()*100,
                t1ld=s['t1_limit_down'].mean()*100,t1lu=s['t1_limit_up'].mean()*100)

print('=== 当前竞价战法（昨日涨停 + 今日高开0~7%）逐日回测 ===')
cur=full[(full['prev_zt'])&(full['op_pct']>0)&(full['op_pct']<=7)]
r=stat(cur,'当前规则')
print('  笔数 %d / 覆盖 %d 天 / 日均 %.1f 笔'%(r['n'],r['days'],r['n']/r['days']))
print('  %-16s 均值%+7.2f%%  胜率%5.1f%%'%('次日开盘卖',r['op_mean'],r['op_win']))
print('  %-16s 均值%+7.2f%%  胜率%5.1f%%'%('次日最高卖(理想)',r['hi_mean'],r['hi_win']))
print('  %-16s 均值%+7.2f%%  胜率%5.1f%%'%('次日收盘卖',r['cl_mean'],r['cl_win']))
print('  次日一字跌停比例 %.1f%% / 一字涨停 %.1f%%'%(r['t1ld'],r['t1lu']))
print('')
print('=== 逐日明细（最近20个交易日）===')
g=cur.groupby('day').agg(n=('r_cl','size'),op=('r_op','mean'),hi=('r_hi','mean'),cl=('r_cl','mean'),
                         win=('r_cl',lambda s:(s>0).mean()*100)).tail(20)
print(g.round(2).to_string())
print('')
print('=== 分时间窗口 ===')
for a,b,lab in [('2024-11-06','2025-05-31','24-11~25-05'),
                ('2025-06-01','2025-12-31','25-06~25-12'),
                ('2026-01-01','2026-06-30','26-01~26-06'),
                ('2026-07-01','2026-11-04','26-07~26-11')]:
    q=cur[(cur['day']>=a)&(cur['day']<=b)]
    if len(q)<30: continue
    print('  %-14s %5d笔 %3d天  次日开%+6.2f%%(胜%4.1f%%)  次高%+6.2f%%(胜%4.1f%%)  次收%+6.2f%%(胜%4.1f%%)'%(
        lab,len(q),q['day'].nunique(),q['r_op'].mean(),(q['r_op']>0).mean()*100,
        q['r_hi'].mean(),(q['r_hi']>0).mean()*100,q['r_cl'].mean(),(q['r_cl']>0).mean()*100))
print('')
print('=== 高开区间细分 ===')
for lo,hi,lab in [(0,1,'0~1%'),(1,2,'1~2%'),(2,3,'2~3%'),(3,5,'3~5%'),(5,7,'5~7%')]:
    q=cur[(cur['op_pct']>lo)&(cur['op_pct']<=hi)]
    if len(q)<30: continue
    print('  %-6s %5d笔  次开%+6.2f%%(胜%4.1f%%)  次高%+6.2f%%(胜%4.1f%%)  次收%+6.2f%%(胜%4.1f%%)'%(
        lab,len(q),q['r_op'].mean(),(q['r_op']>0).mean()*100,
        q['r_hi'].mean(),(q['r_hi']>0).mean()*100,q['r_cl'].mean(),(q['r_cl']>0).mean()*100))
print('')
print('=== 按昨日连板高度 ===')
for lo,hi,lab in [(1,1,'首板'),(2,2,'2板'),(3,3,'3板'),(4,99,'4板+')]:
    q=cur[(cur['prev_bd']>=lo)&(cur['prev_bd']<=hi)]
    if len(q)<30: continue
    print('  %-6s %5d笔  次开%+6.2f%%(胜%4.1f%%)  次高%+6.2f%%(胜%4.1f%%)  次收%+6.2f%%(胜%4.1f%%)'%(
        lab,len(q),q['r_op'].mean(),(q['r_op']>0).mean()*100,
        q['r_hi'].mean(),(q['r_hi']>0).mean()*100,q['r_cl'].mean(),(q['r_cl']>0).mean()*100))
cur.to_pickle('_bt_auction_real.pkl')
print('')
print('明细已存 _bt_auction_real.pkl')
