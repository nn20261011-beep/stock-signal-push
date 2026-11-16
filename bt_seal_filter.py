# -*- coding: utf-8 -*-
"""封板预警口径回测：触板样本按特征分层，看哪类值得推
买入假设：触板价（涨停价）买入，断板次日走、最长 5 日
"""
import os,sys,glob,pickle
import numpy as np,pandas as pd
BASE=os.path.dirname(os.path.abspath(__file__))
MF=pickle.load(open(os.path.join(BASE,'_minfeat2.pkl'),'rb'))
K={}
for fp in glob.glob(os.path.join(BASE,'_kline_raw','*.pkl')):
    c=os.path.basename(fp).replace('.pkl','')
    try: K[c]=pickle.load(open(fp,'rb'))
    except: pass
IDX={}
for c,rec in K.items():
    ds=sorted(rec); IDX[c]=(ds,{d:j for j,d in enumerate(ds)})
print('分钟特征 %d 只 / 日线 %d 只'%(len(MF),len(K)),flush=True)

def trade(code,day,maxhold=5):
    """涨停价买入，断板次日走"""
    if code not in IDX: return None
    ds,pos=IDX[code]; rec=K[code]
    i=pos.get(day)
    if i is None or i+1>=len(ds): return None
    buy=round(rec[ds[i-1]][1]*1.1,2) if i>0 else None
    if not buy or buy<=0: return None
    for k in range(i+1,min(i+1+maxhold,len(ds))):
        chg=(rec[ds[k]][1]/rec[ds[k-1]][1]-1)*100 if k>0 else 0
        if not (9.8<=chg<=10.6):
            kk=min(k+1,len(ds)-1)
            return (rec[ds[kk]][1]/buy-1)*100-0.2, kk-i
    kk=min(i+maxhold,len(ds)-1)
    return (rec[ds[kk]][1]/buy-1)*100-0.2, kk-i

rows=[]
n=0
for c,m in MF.items():
    for d,f in m.items():
        if f.get('zt_touch')!=1: continue
        t=trade(c,d)
        if not t: continue
        ret,hd=t
        rows.append(dict(day=d,code=c,ret=ret,hold=hd,
                         zt_first=f.get('zt_first') or 99,
                         open_cnt=f.get('open_cnt') or 0,
                         vwap=f.get('vwap_ratio') or 0,
                         close_pos=f.get('close_pos') or 0,
                         open_gap=f.get('open_gap') or 0,
                         chg=f.get('chg') or 0,
                         zt_close=f.get('zt_close') or 0))
        n+=1
D=pd.DataFrame(rows)
print('可回测触板样本 %d 笔（有次日数据的）'%len(D),flush=True)
print('')
print('基准：笔均%+.2f%% 胜率%.1f%% 收盘封死率%.1f%%'%(
    D['ret'].mean(),(D['ret']>0).mean()*100,D['zt_close'].mean()*100))
print('')
print('=== 按首封时间分层（zt_first：1=9:30，数字越大越晚）===')
D['seg_first']=pd.cut(D['zt_first'],[-1,15,60,120,180,240,999],
                      labels=['10点前','10-11点','11-12点','13-14点','14-15点','未封'])
for s,g in D.groupby('seg_first',observed=True):
    if len(g)<300: continue
    print('  %-8s %6d 笔  笔均%+7.2f%%  胜率%5.1f%%  封死率%5.1f%%'%(
        s,len(g),g['ret'].mean(),(g['ret']>0).mean()*100,g['zt_close'].mean()*100))
print('')
print('=== 按开板次数分层 ===')
D['seg_open']=pd.cut(D['open_cnt'],[-1,0,1,2,99],labels=['0次(一次封死)','1次','2次','3次以上'])
for s,g in D.groupby('seg_open',observed=True):
    if len(g)<300: continue
    print('  %-12s %6d 笔  笔均%+7.2f%%  胜率%5.1f%%  封死率%5.1f%%'%(
        s,len(g),g['ret'].mean(),(g['ret']>0).mean()*100,g['zt_close'].mean()*100))
print('')
print('=== 按日内位置 close_pos（收盘在当日振幅的位置）===')
D['seg_pos']=pd.cut(D['close_pos'],[0,0.3,0.6,0.9,1.01],labels=['低位<30%','30-60%','60-90%','高位>90%'])
for s,g in D.groupby('seg_pos',observed=True):
    if len(g)<300: continue
    print('  %-10s %6d 笔  笔均%+7.2f%%  胜率%5.1f%%'%(
        s,len(g),g['ret'].mean(),(g['ret']>0).mean()*100))
print('')
print('=== 组合：一次封死 + 收盘高位 + 10点前 ===')
q=D[(D['open_cnt']==0)&(D['close_pos']>=0.9)&(D['zt_first']<=15)]
print('  %d 笔  笔均%+.2f%%  胜率%.1f%%'%(len(q),q['ret'].mean(),(q['ret']>0).mean()*100))
q2=D[(D['open_cnt']>=2)|(D['close_pos']<0.3)]
print('=== 反例：开板≥2次 或 收盘低位 ===')
print('  %d 笔  笔均%+.2f%%  胜率%.1f%%'%(len(q2),q2['ret'].mean(),(q2['ret']>0).mean()*100))
D.to_pickle(os.path.join(BASE,'_seal_filter.pkl'))
print('')
print('明细已存 _seal_filter.pkl')
