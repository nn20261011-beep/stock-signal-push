# -*- coding: utf-8 -*-
"""抓全市场最新日线（新浪，不复权，datalen=260），落盘 _live_kline.pkl"""
import os,json,time,urllib.request,pickle,glob
from concurrent.futures import ThreadPoolExecutor,as_completed
BASE=os.path.dirname(os.path.abspath(__file__))
UA={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
# 用本地全市场代码表，避免 clist 不稳
# 优先用轻量代码表（云端部署用），本地回退到 _kline_raw
_uni=os.path.join(BASE,'universe.json')
if os.path.exists(_uni):
    codes=sorted(json.load(open(_uni,encoding='utf-8')))
else:
    codes=sorted({os.path.basename(f).replace('.pkl','') for f in glob.glob(os.path.join(BASE,'_kline_raw','*.pkl'))})
print('目标 %d 只'%len(codes),flush=True)
def one(c):
    sym=('sh' if c.startswith(('6','5')) else 'sz')+c
    u='https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketData.getKLineData?symbol=%s&scale=240&ma=no&datalen=260'%sym
    for k in range(2):
        try:
            a=json.loads(urllib.request.urlopen(urllib.request.Request(u,headers=UA),timeout=15).read().decode())
            if not a: return c,None
            out={}
            for x in a:
                d=str(x['day'])[:10]
                prev=None
                out[d]=(float(x['open']),float(x['close']),float(x['high']),float(x['low']),float(x['volume']))
            return c,out
        except Exception:
            time.sleep(0.25)
    return c,None
res={};t0=time.time()
with ThreadPoolExecutor(max_workers=10) as ex:
    for i,f in enumerate(as_completed([ex.submit(one,c) for c in codes])):
        c,v=f.result()
        if v: res[c]=v
        if (i+1)%500==0: print('  %d/%d 成功%d 用时%.0fs'%(i+1,len(codes),len(res),time.time()-t0),flush=True)
pickle.dump(res,open(os.path.join(BASE,'_live_kline.pkl'),'wb'))
allday=set()
for v in res.values(): allday|=set(v.keys())
print('完成 %d 只 / 最新交易日 %s / 用时 %.0fs'%(len(res),max(allday),time.time()-t0),flush=True)
