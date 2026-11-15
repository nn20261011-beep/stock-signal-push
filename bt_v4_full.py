# -*- coding: utf-8 -*-
"""逐笔组合回测 v4 完整版
买点：open=次日开盘 / seal=次日打板（触板且非一字，以涨停价成交）
卖点：按票类（龙头/前排=rbreak 断板次日走；趋势=sl5；补涨=r10）
心法：红线1主线(题材涨停>=3) / 红线2低开不做 / 红线3高开>7%不做 / 红线6单票<=10% / 红线7持仓<=8
纪律：连亏3停手 / 单日-5%次日减半 / 回撤-20%熔断(空仓20天)
模式：近20笔均值<0降半，<-3%停手
"""
import os,sys,json,gzip,pickle
import pandas as pd,numpy as np
BASE=os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0,os.path.join(BASE,'_gh_lib'))
import regime,four_type,sizing

print('[1/3] 载入',flush=True)
E=pd.read_pickle(os.path.join(BASE,'_events3.pkl'))
E=E[E['day']>='2016-01-01'].copy()
mx=E.groupby('day')['bd'].max().to_dict()
E['type']=four_type.tag(E,mx)
M=pd.read_pickle(os.path.join(BASE,'_regime_base.pkl'))
env={r['day']:(r['zt_n'],r['dt_n'],r['max_bd'],r['earn']) for _,r in M.iterrows()}
days=sorted(E['day'].unique())
byday={d:g for d,g in E[E['type']!=''].groupby('day')}
# 用全历史日线（_hist 只留最近320根，2016-2024 取不到次日开盘价）
import glob
K={}
for fp in glob.glob(os.path.join(BASE,'_kline_raw','*.pkl')):
    c=os.path.basename(fp).replace('.pkl','')
    try: K[c]=pickle.load(open(fp,'rb'))
    except Exception: pass
MF=pickle.load(open(os.path.join(BASE,'_minfeat2.pkl'),'rb')) if os.path.exists(os.path.join(BASE,'_minfeat2.pkl')) else {}
print('  事件 %d / 交易日 %d / 有票类 %d / 分钟特征 %d 只'%(len(E),len(days),len(byday),len(MF)),flush=True)

IDX={}
for c,rec in K.items():
    ds=sorted(rec); IDX[c]=(ds,{d:j for j,d in enumerate(ds)})

def nx(code,day):
    if code not in IDX: return None
    ds,pos=IDX[code]
    j=pos.get(day)
    if j is None or j+1>=len(ds): return None
    nd=ds[j+1]
    return nd, K[code][nd][0], K[code][day][1]

def seal_trade(code,sig_day,maxhold=10):
    """打板：次日触板且非一字，以涨停价买；断板次日走"""
    if code not in IDX: return None
    ds,pos=IDX[code]; rec=K[code]
    i=pos.get(sig_day)
    if i is None or i+1>=len(ds): return None
    nd=ds[i+1]; limit=round(rec[ds[i]][1]*1.1,2)
    mf=MF.get(code,{}).get(nd)
    if not mf or mf.get('zt_touch')!=1: return None
    if abs(rec[nd][0]-limit)<0.011: return None
    buy=limit
    for k in range(i+1,min(i+1+maxhold,len(ds)-1)):
        d=ds[k]; chg=(rec[d][1]/rec[ds[k-1]][1]-1)*100 if k>0 else 0
        if not (9.8<=chg<=10.6):
            kk=min(k+1,len(ds)-1)
            return (rec[ds[kk]][1]/buy-1)*100-0.1, kk-i
    kk=min(i+1+maxhold,len(ds)-1)
    return (rec[ds[kk]][1]/buy-1)*100-0.1, kk-i

SELL={'龙头':'rbreak','前排':'rbreak','趋势':'sl5','补涨':'r10'}
HOLD={'龙头':2.5,'前排':2.5,'趋势':2.0,'补涨':2.0}

def run(entry='open', use_gap=True, use_streak=True, use_halt=True,
        use_mode=True, cap=0.8, gap_lo=0.0, gap_hi=7.0):
    cash=1.0; pos=[]; nav=[]; peak=1.0; halt_left=0
    trades=0; wins=0; loss_streak=0; recent=[]; day_cost=0.0; day_pnl=0.0
    last_daily=0.0; daily_half=False; mode_cool=0
    for i,d in enumerate(days):
        keep=[]
        for sd,v,win,c0 in pos:
            if sd<=i:
                cash+=v
                day_cost+=c0; day_pnl+=(v-c0)
                if win: wins+=1
            else: keep.append((sd,v,win,c0))
        pos=keep
        if day_cost>0:
            pnl_pct=day_pnl/day_cost*100
            if pnl_pct<0: loss_streak+=1
            else: loss_streak=0
            last_daily=pnl_pct
            day_cost=0.0; day_pnl=0.0
        if use_streak and loss_streak>=3:
            loss_streak=0; nav.append(cash+sum(v for _,v,_,_ in pos)); continue
        if use_streak and last_daily<=-5.0:
            daily_half=True
        else:
            daily_half=False
        cur=cash+sum(v for _,v,_,_ in pos); peak=max(peak,cur)
        if use_halt and cur/peak-1<=-0.20: halt_left=20
        if halt_left>0: halt_left-=1; nav.append(cur); continue
        if d not in env: nav.append(cur); continue
        st,act,why=regime.classify(*env[d])
        if act=='不做': nav.append(cur); continue
        p=regime.params(act)
        cap_eff=min(cap,p['exposure'])
        if use_mode:
            if mode_cool>0:
                mode_cool-=1; nav.append(cur); continue
            if len(recent)>=10:
                avg=sum(recent[-20:])/len(recent[-20:])
                if avg<=-3.0:
                    mode_cool=5; recent=[]      # 停 5 天后重新评估，避免死锁
                    nav.append(cur); continue
                if avg<0:
                    cap_eff*=0.5
        g=byday.get(d)
        if g is None or not len(g): nav.append(cur); continue
        usable=[tp for tp in four_type.TYPES if st in four_type.TYPES[tp]['stages']]
        cand=g[g['type'].isin(usable)].copy()
        if not len(cand): nav.append(cur); continue
        # 心法1：主线（题材涨停>=3）——用 c_zt 字段近似
        if 'c_zt' in cand.columns:
            cand=cand[cand['c_zt']>=1]
        if not len(cand): nav.append(cur); continue
        cand['deq']=cand['type'].map(lambda t:(sizing.weight_for(t,st)[1] or 0))
        cand=cand.sort_values(['deq','chg'],ascending=False)
        picks=cand.head(min(p['max_picks'],8))
        if daily_half: cap_eff*=0.5
        per=min(0.10, cap_eff/max(len(picks),1), cash/max(len(picks),1))
        if per<=0.001: nav.append(cur); continue
        for _,r in picks.iterrows():
            c=r['code']
            if entry=='seal':
                t=seal_trade(c,d)
                if not t: continue
                ret,hd=t
                # 打板当日买不到次日卖，持有 hd 天
                amt=per
                if amt>cash: continue
                cash-=amt
                pos.append((i+1+hd, amt*(1+ret/100), ret>0, amt))
                trades+=1; recent.append(ret)
            else:
                # 开盘买：先做 gap 过滤
                if use_gap:
                    n=nx(c,d)
                    if not n: continue
                    nd,no,pc=n
                    if pc<=0: continue
                    gp=(no/pc-1)*100
                    if gp<=gap_lo or gp>gap_hi: continue
                ret=float(r['r1'])
                if not np.isfinite(ret): continue
                amt=per
                if amt>cash: continue
                cash-=amt
                pos.append((i+1, amt*(1+ret/100), ret>0, amt))
                trades+=1; recent.append(ret)
        nav.append(cash+sum(v for _,v,_,_ in pos))
    nav=np.array(nav); pk=np.maximum.accumulate(nav)
    return dict(nav=nav[-1],ann=(nav[-1]**(240/len(nav))-1)*100 if nav[-1]>0 else -99,
                mdd=((nav/pk)-1).min()*100,vol=np.diff(nav).std()/nav[:-1].mean()*100,
                trades=trades,win=(wins/trades*100 if trades else 0),days=len(nav))

print('[2/3] 回测',flush=True)
plans=[
 ('A 全开·开盘买·有gap过滤',dict(entry='open',use_gap=True,use_streak=True,use_halt=True,use_mode=True)),
 ('B 全开·开盘买·无gap过滤',dict(entry='open',use_gap=False,use_streak=True,use_halt=True,use_mode=True)),
 ('C 无纪律·开盘买·有gap',dict(entry='open',use_gap=True,use_streak=False,use_halt=False,use_mode=False)),
 ('D 全开·打板买',dict(entry='seal',use_gap=True,use_streak=True,use_halt=True,use_mode=True)),
 ('E 全开·开盘买·总仓50%',dict(entry='open',use_gap=True,use_streak=True,use_halt=True,use_mode=True,cap=0.5)),
 ('F 只拦高开>7%·不拦低开',dict(entry='open',use_gap=True,use_streak=True,use_halt=True,use_mode=True,gap_lo=-99.0)),
 ('G 只拦高开>9%·不拦低开',dict(entry='open',use_gap=True,use_streak=True,use_halt=True,use_mode=True,gap_lo=-99.0,gap_hi=9.0)),
 ('H 拦低开>2%·拦高开>7%',dict(entry='open',use_gap=True,use_streak=True,use_halt=True,use_mode=True,gap_lo=2.0)),
]
print('%-30s %7s %9s %9s %8s %7s'%('方案','笔数','年化','最大回撤','日波动','胜率'))
res=[]
for name,kw in plans:
    r=run(**kw); res.append((name,r))
    print('%-30s %7d %+8.1f%% %+8.1f%% %7.2f%% %6.1f%%'%(
        name,r['trades'],r['ann'],r['mdd'],r['vol'],r['win']),flush=True)
json.dump({n:{k:round(v,3) if isinstance(v,float) else v for k,v in r.items()} for n,r in res},
          open(os.path.join(BASE,'_bt_v4_full.json'),'w',encoding='utf-8'),ensure_ascii=False,indent=1)
print('')
print('[3/3] 已存 _bt_v4_full.json')
