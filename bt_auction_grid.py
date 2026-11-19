# -*- coding: utf-8 -*-
"""竞价战法参数网格：找高胜率组合（目标 70%+ 胜率、3%+ 收益）"""
import pandas as pd,numpy as np,pickle
D=pd.read_pickle('_bt_auction_real.pkl')
base=D[(D['prev_zt'])&(D['op_pct']>0)&(D['op_pct']<=7)].copy()
print('基础样本 %d 笔 / %d 天'%(len(base),base['day'].nunique()))
print('')
def show(q,label,minn=60):
    if len(q)<minn: return None
    d=q['day'].nunique()
    return (label,len(q),d,q['r_op'].mean(),(q['r_op']>0).mean()*100,
            q['r_hi'].mean(),(q['r_hi']>0).mean()*100,
            q['r_cl'].mean(),(q['r_cl']>0).mean()*100)
HDR='%-30s %6s %5s %8s %7s %8s %7s %8s %7s'
def pr(r):
    if not r: return
    print(HDR%(r[0],r[1],r[2],'%+.2f%%'%r[3],'%.0f%%'%r[4],'%+.2f%%'%r[5],'%.0f%%'%r[6],'%+.2f%%'%r[7],'%.0f%%'%r[8]))
print('=== 单维度：量比 vr ===')
print(HDR%('条件','笔数','天','次开','胜率','次高','胜率','次收','胜率'))
for lo,hi,lab in [(0,0.8,'vr<0.8'),(0.8,1.5,'vr 0.8-1.5'),(1.5,3,'vr 1.5-3'),(3,99,'vr>3')]:
    pr(show(base[(base['vr']>lo)&(base['vr']<=hi)],lab))
print('')
print('=== 单维度：换手 tov ===')
print(HDR%('条件','笔数','天','次开','胜率','次高','胜率','次收','胜率'))
for lo,hi,lab in [(0,3,'tov<3'),(3,8,'tov 3-8'),(8,15,'tov 8-15'),(15,99,'tov>15')]:
    pr(show(base[(base['tov']>lo)&(base['tov']<=hi)],lab))
print('')
print('=== 单维度：位置 p60 ===')
print(HDR%('条件','笔数','天','次开','胜率','次高','胜率','次收','胜率'))
for lo,hi,lab in [(0,30,'p60<30 低位'),(30,70,'p60 30-70'),(70,101,'p60>70 高位')]:
    pr(show(base[(base['p60']>=lo)&(base['p60']<hi)],lab))
print('')
print('=== 组合：3板 + 各维度 ===')
b3=base[base['prev_bd']==3]
print('  3板基础: %d 笔 %d 天'%(len(b3),b3['day'].nunique()))
print(HDR%('条件','笔数','天','次开','胜率','次高','胜率','次收','胜率'))
pr(show(b3,'3板全部',30))
for lo,hi,lab in [(0,1.5,'+vr<=1.5'),(1.5,99,'+vr>1.5')]:
    pr(show(b3[(b3['vr']>lo)&(b3['vr']<=hi)],'3板'+lab,20))
for lo,hi,lab in [(0,8,'+tov<8'),(8,99,'+tov>8')]:
    pr(show(b3[(b3['tov']>lo)&(b3['tov']<=hi)],'3板'+lab,20))
for lo,hi,lab in [(0,50,'+p60<50'),(50,101,'+p60>50')]:
    pr(show(b3[(b3['p60']>=lo)&(b3['p60']<hi)],'3板'+lab,20))
for lo,hi,lab in [(0,3,'+高开0-3'),(3,7,'+高开3-7')]:
    pr(show(b3[(b3['op_pct']>lo)&(b3['op_pct']<=hi)],'3板'+lab,20))
print('')
print('=== 组合：2板+3板 合并 + 条件 ===')
b23=base[base['prev_bd'].isin([2,3])]
print(HDR%('条件','笔数','天','次开','胜率','次高','胜率','次收','胜率'))
pr(show(b23,'2-3板全部',60))
pr(show(b23[b23['vr']>1.5],'+vr>1.5',40))
pr(show(b23[b23['p60']<50],'+p60<50',40))
pr(show(b23[(b23['vr']>1.5)&(b23['p60']<50)],'+vr>1.5&p60<50',20))
print('')
print('=== 逐日胜率分布（3板+，看是否稳定）===')
q=b3.copy()
g=q.groupby('day').agg(n=('r_hi','size'),hi=('r_hi','mean'),win=('r_hi',lambda s:(s>0).mean()*100))
print('  覆盖 %d 天，日均 %.1f 笔'%(len(g),g['n'].mean()))
print('  次日最高卖：日均收益>0 的天数 %d/%d = %.0f%%'%((g['hi']>0).sum(),len(g),(g['hi']>0).mean()*100))
print('  逐日全胜（当天全涨）的天数 %d/%d'%((g['win']==100).sum(),len(g)))
print(g.tail(15).round(1).to_string())
