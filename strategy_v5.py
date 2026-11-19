# -*- coding: utf-8 -*-
"""v5 打板策略：涨停 + 缩量 + 小振幅 + 前5日强势 → 打板买入 → 次日开盘卖出
依据：9.9万条涨停样本，组合筛选后 3695 笔（排除一字板 543 笔可买）
可买样本：次日开盘卖 +5.79%，胜率 86.0%，三段 +6.40/+5.89/+5.49
"""
import os,glob,pickle
import numpy as np,pandas as pd
BASE=os.path.dirname(os.path.abspath(__file__))
OUT=os.path.join(BASE,'_dataset')

# 阈值（全样本 20% 分位，实盘建议用滚动 250 日分位重算）
TH=dict(vr_max=1.073, amp_max=6.48, r5_min=25.84, gap_open_max=9.5)

def load_kline():
    K={}
    for fp in glob.glob(os.path.join(BASE,'_kline_raw','*.pkl')):
        c=os.path.basename(fp).replace('.pkl','')
        try: K[c]=pickle.load(open(fp,'rb'))
        except: pass
    return K

def candidates(K, day):
    """给定日期，找出符合 v5 条件的涨停票（当日已收盘）"""
    out=[]
    for c,rec in K.items():
        ds=sorted(rec)
        if day not in ds: continue
        j=ds.index(day)
        if j<25: continue
        C=[rec[d][1] for d in ds]; O=[rec[d][0] for d in ds]
        H=[rec[d][2] for d in ds]; L=[rec[d][3] for d in ds]; V=[rec[d][4] for d in ds]
        prev=C[j-1]
        if prev<=0: continue
        chg=(C[j]/prev-1)*100
        lim=20.0 if c.startswith(('30','68')) else 10.0
        if not (lim-0.3<=chg<=lim+0.6): continue          # 必须涨停
        v20=sum(V[j-19:j+1])/20
        vr=V[j]/v20 if v20>0 else 99
        amp=(H[j]-L[j])/prev*100
        r5=(C[j]/C[j-6]-1)*100 if j>=6 else 99
        open_gap=(O[j]/prev-1)*100
        if vr>TH['vr_max']: continue                       # 缩量
        if amp>TH['amp_max']: continue                     # 小振幅
        if r5<TH['r5_min']: continue                        # 前5日强势
        if open_gap>=TH['gap_open_max']: continue           # 排除一字板（买不到）
        out.append(dict(code=c,day=day,close=C[j],prev=prev,chg=round(chg,2),
                        vr=round(vr,3),amp=round(amp,2),r5=round(r5,2),
                        open_gap=round(open_gap,2),buy=C[j]))
    return out

if __name__=='__main__':
    import sys
    K=load_kline()
    day=sys.argv[1] if len(sys.argv)>1 else '2026-11-13'
    r=candidates(K,day)
    print('=== v5 策略 %s ==='%day)
    print('阈值: vr<=%.3f  amp<=%.2f%%  r5>=%.2f%%  开盘涨幅<%.1f%%'%(
        TH['vr_max'],TH['amp_max'],TH['r5_min'],TH['gap_open_max']))
    print('选出 %d 只'%len(r))
    for x in r:
        print('  %-8s 收%.2f 涨停%.2f%% 量比%.2f 振幅%.2f%% 前5日%+.1f%% 开盘%+.2f%%'%(
            x['code'],x['close'],x['chg'],x['vr'],x['amp'],x['r5'],x['open_gap']))
    if not r: print('  今日无符合条件的标的（空仓）')
