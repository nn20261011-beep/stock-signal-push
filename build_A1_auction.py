# -*- coding: utf-8 -*-
"""A1 竞价撮合库：对每个交易日，取「前一日涨停」的票列表，批量抓当日 09:25 竞价
产出 _dataset/auction.parquet: code, day, auc_price, auc_vol, auc_orders, pre_close
"""
import os,sys,time,pickle,glob
import pandas as pd
import eltdx
BASE=os.path.dirname(os.path.abspath(__file__))
OUT=os.path.join(BASE,'_dataset'); os.makedirs(OUT,exist_ok=True)

# 1. 建每日涨停名单（从本地日线）
print('[1] 建每日涨停名单',flush=True)
ZTP=os.path.join(OUT,'zt_daily.parquet')
if os.path.exists(ZTP):
    ZT=pd.read_parquet(ZTP)
    print('  复用缓存 %d 条 / %d 天'%(len(ZT),ZT['day'].nunique()),flush=True)
    K=None
else:
  K={}
  for fp in glob.glob(os.path.join(BASE,'_kline_raw','*.pkl')):
    c=os.path.basename(fp).replace('.pkl','')
    try: K[c]=pickle.load(open(fp,'rb'))
    except: pass
  print('  日线 %d 只'%len(K),flush=True)
  rows=[]
  for c,rec in K.items():
    ds=sorted(rec)
    for i,d in enumerate(ds):
        if i==0: continue
        p=rec[ds[i-1]][1]
        if p<=0: continue
        chg=(rec[d][1]/p-1)*100
        lim=20.0 if c.startswith(('30','68')) else 10.0
        if lim-0.3<=chg<=lim+0.6:
            rows.append((c,d))
  ZT=pd.DataFrame(rows,columns=['code','day'])
  print('  涨停记录 %d 条 / %d 天'%(len(ZT),ZT['day'].nunique()),flush=True)
  ZT.to_parquet(ZTP,index=False)

# 2. 每个交易日，取前一日涨停的票
days=sorted(ZT['day'].unique())
byt=ZT.groupby('day')['code'].apply(list).to_dict()   # 一次分组，避免 O(n^2)
prev={}
for i,d in enumerate(days):
    if i==0: continue
    prev[d]=byt.get(days[i-1],[])
print('  需要抓取 %d 个交易日'%len(prev),flush=True)

# 3. 按日批量抓竞价
print('[2] 抓取竞价撮合',flush=True)
c=eltdx.Client(timeout=20); c.connect()
LIMIT=int(os.environ.get('LIMIT_DAYS','0') or 0)
START=int(os.environ.get('START_IDX','0') or 0)
items=sorted(prev.items())
TAIL=int(os.environ.get('TAIL_DAYS','0') or 0)
OFF=int(os.environ.get('OFFSET','0') or 0)
if TAIL:
    end=len(items)-OFF
    items=items[max(0,end-TAIL):end]
elif LIMIT: items=items[START:START+LIMIT]
recs=[]; ok=0; fail=0; t0=time.time()
CHUNK=20
for i,(d,codes) in enumerate(items):
    if len(codes)==0: continue
    # 只取主板/创业板，最多 120 只/天（覆盖绝大多数）
    codes=codes[:120]
    try:
        r=c.trades.opening_match_history(codes,d)
        if not isinstance(r,dict): r={}
        for code,v in r.items():
            if v is None: continue
            recs.append(dict(code=code,day=d,
                             auc_price=float(v.price),
                             auc_vol=int(v.volume),
                             auc_orders=int(v.order_count)))
            ok+=1
    except Exception as e:
        fail+=1
    if (i+1)%CHUNK==0:
        pd.DataFrame(recs).to_parquet(os.path.join(OUT,'auction_part%d.parquet'%(START+i+1)),index=False)
        el=time.time()-t0
        print('  %d/%d  成功%d 失败%d  已用 %.1f 分  已落盘分片'%(
            i+1,len(items),ok,fail,el/60),flush=True)
c.close()
D=pd.DataFrame(recs)
seg='%s_%s'%(items[0][0],items[-1][0]) if items else 'empty'
fp=os.path.join(OUT,'auction_%s.parquet'%seg)
D.to_parquet(fp,index=False)
print('分片文件 %s'%os.path.basename(fp),flush=True)
print('')
print('完成：%d 条 / %d 天 / %d 只'%(len(D),D['day'].nunique(),D['code'].nunique()),flush=True)
print('存 _dataset/auction.parquet',flush=True)
