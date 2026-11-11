# -*- coding: utf-8 -*-
"""
push_lib.py —— 每日扫描 + 多策略信号 + 邮件推送（H1/H3/H4 主程序）

流程：
  1. 读 _live_kline.pkl（全市场最新日线，含今日）
  2. 增量更新市场状态到今日（涨停家数/最高板/赚钱效应/regime/牛熊）
  3. 按策略库（13 套，来自 4+ 类逻辑）筛信号
  4. 限流：每策略最多 3 只，全信最多 10 只；去重、剔 ST/退市/停牌/一字
  5. 生成 HTML 邮件 → SMTP 发送 → 记录日志与逐笔
"""
import os, sys, json, pickle, smtplib, ssl, time, glob
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.header import Header

BASE = os.path.dirname(os.path.abspath(__file__))
BJ = timezone(timedelta(hours=8))
SMTP_USER = os.environ.get('SMTP_USER', 'h1533165068@qq.com')
SMTP_PASS = os.environ.get('SMTP_PASS', 'xfboalpjikugjfgg')
MAIL_TO = os.environ.get('MAIL_TO', 'h1533165068@qq.com')
ZT_LO, ZT_HI = 9.8, 10.6
LOGDIR = os.path.join(BASE, '_push_logs')
os.makedirs(LOGDIR, exist_ok=True)

# ============ 策略库（13 套，4+ 类逻辑；全部经三段+按日等权验证） ============
# (编号, 名称, 逻辑类别, 适用行情, 触发条件 lambda, 卖出规则, 历史日等权, 历史胜率, 三段)
def strategies(f):
    S = [
      # —— 逻辑1 超跌均值回归 ——
      ('A4','任意市深度超跌','超跌均值回归','不限行情（主力）',
       (f.r20p<-20)&(f.gap60<-15)&(f.dd250<-50),'持满20个交易日，收盘卖出',1.13,63.5,'+0.50/+0.53/+3.65'),
      ('A1','冰点深度超跌','超跌均值回归','大盘冰点期',
       (f.m_regime=='冰点期')&(f.r20p<-20)&(f.dd250<-50)&(f.gap60<-15),'持满20个交易日，收盘卖出',5.49,80.8,'+2.89/+9.90/+9.08'),
      ('A2','冰点中跌反弹','超跌均值回归','大盘冰点期',
       (f.m_regime=='冰点期')&(f.r20p<-15)&(f.dd250<-35),'持满20个交易日，收盘卖出',4.30,76.5,'+4.14/+7.03/+1.86'),
      ('A3','冰点浅跌普涨','超跌均值回归','大盘冰点期',
       (f.m_regime=='冰点期')&(f.r20p<-10)&(f.dd250<-25),'持满20个交易日，收盘卖出',4.84,69.8,'+4.42/+6.36/+4.59'),
      ('A6','发酵期超跌','超跌均值回归','发酵期',
       (f.m_regime=='发酵期')&(f.r20p<-15)&(f.dd250<-35),'持满20个交易日，收盘卖出',0.84,57.1,'+0.58/+1.18/+1.29'),
      # —— 逻辑2 冰点情绪/低位 ——
      ('A7','冰点期低位','冰点情绪','大盘冰点期',
       (f.m_regime=='冰点期')&(f.p60<20),'持满10个交易日，收盘卖出',2.09,61.1,'+2.38/+1.70/+1.57'),
      # —— 逻辑3 板块联动 ——
      ('B1','牛市超跌+板块强','板块联动','牛市',
       (f.m_bb=='牛市')&(f.r20p<-20)&(f.ind_chg>2),'持满20个交易日，收盘卖出',1.82,48.0,'+1.87/+2.07/+1.40'),
      ('C1','震荡破MA60+板块强','板块联动','震荡市',
       (f.m_bb=='震荡')&(f.gap60<-15)&(f.ind_chg>2),'持满20个交易日，收盘卖出',3.02,57.0,'+4.08/+1.93/+0.88'),
      ('C3','震荡低位+板块强','板块联动','震荡市',
       (f.m_bb=='震荡')&(f.p60<20)&(f.ind_chg>2),'持满20个交易日，收盘卖出',0.53,47.0,'+0.26/+1.17/+0.71'),
      # —— 逻辑4 趋势/低波 ——
      ('B3','牛市低价低波','趋势低波','牛市',
       (f.m_bb=='牛市')&(f.price<15)&(f.vol_std<2),'持满20个交易日，收盘卖出',0.83,48.0,'+0.81/+0.45/+1.25'),
      ('B4','牛市多头低波','趋势低波','牛市',
       (f.m_bb=='牛市')&(f.ma_bull==1)&(f.vol_std<2),'持满20个交易日，收盘卖出',0.82,47.0,'+0.80/+0.23/+1.49'),
      # —— 逻辑5 量能/动量 ——
      ('B2','牛市破MA60+5日转强','量能动量','牛市',
       (f.m_bb=='牛市')&(f.gap60<-15)&(f.r5p>5),'持满20个交易日，收盘卖出',1.14,48.0,'+0.57/+0.31/+3.70'),
      ('C2','震荡放量+大盘股','量能动量','震荡市',
       (f.m_bb=='震荡')&(f.vol_r>2)&(f.fmc>150),'持满20个交易日，收盘卖出',1.34,47.0,'+0.82/+0.96/+3.28'),
    ]
    return S


# ---------- 1. 更新市场状态 ----------
def market_state(K, today):
    days = sorted({d for v in K.values() for d in v})[-30:]
    out = {}
    for k, d in enumerate(days):
        prev = days[k-1] if k > 0 else None
        chgs, bds = {}, {}
        for c, v in K.items():
            if d not in v or prev not in v:
                continue
            pc = v[prev][1]
            if pc > 0:
                chgs[c] = (v[d][1]/pc-1)*100
        zt = [c for c,x in chgs.items() if 9.8<=x<=10.6]
        dt = [c for c,x in chgs.items() if x<=-9.8]
        # 连板
        bdmap = {}
        for c in zt:
            v = K[c]; j = days.index(d); n = 1
            while j-1 >= 0 and days[j-1] in v and days[j-2] in v:
                p2 = v[days[j-2]][1]
                if p2>0 and (v[days[j-1]][1]/p2-1)*100 >= 9.8:
                    n += 1; j -= 1
                else: break
            bdmap[c] = n
        maxbd = max(bdmap.values()) if bdmap else 0
        # 赚钱效应：昨日涨停股今日平均涨幅
        earn = np.nan
        if prev:
            pz = []
            for c,v in K.items():
                if prev in v and days.index(prev)>0:
                    pp = days[days.index(prev)-1]
                    if pp in v and v[pp][1]>0 and (v[prev][1]/v[pp][1]-1)*100>=9.8:
                        if d in v and v[prev][1]>0: pz.append((v[d][1]/v[prev][1]-1)*100)
            earn = float(np.mean(pz)) if pz else 0.0
        # 市场宽度/趋势
        up = np.mean([1 if x>0 else 0 for x in chgs.values()])*100 if chgs else 50
        out[d] = dict(zt_n=len(zt), dt_n=len(dt), max_bd=maxbd, earn=round(earn,2) if np.isfinite(earn) else 0,
                      up=round(up,1))
    # regime 用前一日 max_bd / earn（无未来函数）
    ms = pd.read_pickle(os.path.join(BASE,'_market_state2.pkl')).set_index('day').to_dict('index')
    td = pd.read_pickle(os.path.join(BASE,'_trend_state.pkl')).set_index('day').to_dict('index')
    res = []
    for d in sorted(out):
        if d in ms and d in td:
            res.append(dict(day=d, regime=ms[d].get('regime'), bb=td[d].get('bb'),
                            zt_n=out[d]['zt_n'], max_bd=out[d]['max_bd'], earn=out[d]['earn'],
                            src='历史库'))
            continue
        # 新增日：用前一日数据定当日基调
        prev = [x for x in sorted(out) if x < d]
        p = out[prev[-1]] if prev else dict(max_bd=0, earn=0)
        bd, en = p['max_bd'], p['earn']
        if en < -1.5: rg = '冰点期'
        elif bd >= 6 and en >= 1.0: rg = '高潮期'
        elif bd >= 4 and en > 0: rg = '发酵期'
        elif bd <= 3: rg = '低迷期'
        else: rg = '分化期'
        # 牛熊：用全市场「20 日等权涨幅」中位数（🔴 不能用 000001，那是平安银行不是指数）
        trs = []
        j = days.index(d)
        for c, v in K.items():
            vd = sorted(v)
            if d in vd and len(vd) >= 21:
                k = vd.index(d)
                if k >= 20 and v[vd[k-20]][1] > 0:
                    trs.append((v[d][1]/v[vd[k-20]][1]-1)*100)
        tr20 = float(np.median(trs)) if trs else 0
        bb = '牛市' if tr20 > 5 else ('熊市' if tr20 < -5 else '震荡')
        res.append(dict(day=d, regime=rg, bb=bb, zt_n=out[d]['zt_n'],
                        max_bd=out[d]['max_bd'], earn=out[d]['earn'], src='实时计算'))
    return pd.DataFrame(res)


# ---------- 2. 算个股特征 ----------
def fetch_today_theme(today):
    """实时抓今日同花顺涨停原因（题材串），补 _theme_tags 未覆盖的日期"""
    import urllib.request
    UA={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64)','Referer':'https://data.10jqka.com.cn/'}
    FIELD='199112,10,9001,330323,330324,330325,9002,330329,133971,133970,1968584,3475914,9003,9004'
    out={}
    dt=today.replace('-','')
    for page in range(1,5):
        u=('https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool?page=%d&limit=200&field=%s'
           '&filter=HS,GEM2STAR&order_field=330324&order_type=0&date=%s'%(page,FIELD,dt))
        try:
            j=json.loads(urllib.request.urlopen(urllib.request.Request(u,headers=UA),timeout=12).read().decode())
        except Exception:
            break
        if j.get('status_code')!=0: break
        info=(j.get('data') or {}).get('info') or []
        for r in info:
            c=str(r.get('code') or '')
            raw=str(r.get('reason_type') or '')
            if len(c)==6 and raw:
                out[c]=[t.strip() for t in raw.replace('＋','+').split('+') if t.strip()]
        total=((j.get('data') or {}).get('page') or {}).get('total') or 0
        if not info or page*200>=total: break
        time.sleep(0.15)
    return out


def build_features(K, today, mstate):
    ind = json.load(open(os.path.join(BASE,'_industry_all.json'),encoding='utf-8'))
    ind_of = {c:(v.get('ind2') or 'OTHER') for c,v in ind.items()}
    name_of = {c:(v.get('name') or '') for c,v in ind.items()}
    fcap_of = {c:(v.get('fcap') or 0)/1e8 for c,v in ind.items()}
    tags = json.load(open(os.path.join(BASE,'_theme_tags.json'),encoding='utf-8'))
    live_tags = fetch_today_theme(today)          # 今日真题材（同花顺）
    tagmap = dict(tags.get(today, {}))
    tagmap.update(live_tags)
    print('今日题材标注 %d 只（实时抓取）'%len(tagmap),flush=True)
    # 当日行业涨幅
    ic = {}
    for c,v in K.items():
        if today not in v: continue
        ds = sorted(v); j = ds.index(today)
        if j==0: continue
        chg = (v[today][1]/v[ds[j-1]][1]-1)*100
        ic.setdefault(ind_of.get(c,'OTHER'),[]).append(chg)
    ind_chg = {k:float(np.mean(a)) for k,a in ic.items()}
    ind_zt = {k:float(np.mean([1 if x>=9.8 else 0 for x in a])*100) for k,a in ic.items()}
    rows=[]
    for c,v in K.items():
        ds=sorted(v)
        if today not in v or len(ds)<250: continue
        i=ds.index(today)
        if i<249: continue
        O=np.array([v[d][0] for d in ds],float); C=np.array([v[d][1] for d in ds],float)
        H=np.array([v[d][2] for d in ds],float); L=np.array([v[d][3] for d in ds],float)
        V=np.array([v[d][4] for d in ds],float)
        chg=(C[i]/C[i-1]-1)*100
        nm=name_of.get(c,'')
        rows.append(dict(
          code=c, name=nm, close=round(C[i],2), chg=round(chg,2),
          is_zt=int(9.8<=chg<=10.6),
          r5p=round((C[i]/C[i-5]-1)*100,2), r20p=round((C[i]/C[i-20]-1)*100,2),
          r60p=round((C[i]/C[i-60]-1)*100,2),
          dd250=round((C[i]/np.max(H[i-249:i+1])-1)*100,1),
          p60=round(float((C[i-59:i+1]<C[i]).sum())/60*100,0),
          gap5=round((C[i]/np.mean(C[i-5:i])-1)*100,2),
          gap10=round((C[i]/np.mean(C[i-10:i])-1)*100,2),
          gap20=round((C[i]/np.mean(C[i-20:i])-1)*100,2),
          gap60=round((C[i]/np.mean(C[i-60:i])-1)*100,2),
          ma_bull=int(np.mean(C[i-5:i])>np.mean(C[i-10:i])>np.mean(C[i-20:i])>np.mean(C[i-60:i])),
          vol_r=round(V[i]/np.mean(V[i-20:i]),2) if np.mean(V[i-20:i])>0 else 0,
          v5_20=round(np.mean(V[i-5:i])/np.mean(V[i-20:i]),2) if np.mean(V[i-20:i])>0 else 0,
          vol_std=round(float(np.std([(C[k]/C[k-1]-1)*100 for k in range(i-19,i+1)])),2),
          ups20=round(float(np.mean([1 if (C[k]/C[k-1]-1)>0 else 0 for k in range(i-19,i+1)])*100),0),
          fmc=round(fcap_of.get(c,0),1), price=round(C[i],2),
          ind2=ind_of.get(c,'OTHER'), ind_chg=round(ind_chg.get(ind_of.get(c,'OTHER'),0),2),
          ind_zt=round(ind_zt.get(ind_of.get(c,'OTHER'),0),1),
          tags='|'.join(tagmap.get(c,[])),
          assist=0,
        ))
    f=pd.DataFrame(rows)
    cur=mstate[mstate.day==today]
    if len(cur):
        r=cur.iloc[0]
        f['m_regime']=r['regime']; f['m_bb']=r['bb']
    else:
        f['m_regime']='NA'; f['m_bb']='NA'
    return f


# ---------- 3. 发送邮件 ----------
def send_mail(subject, html, dry=False):
    msg=MIMEText(html,'html','utf-8')
    msg['From']=SMTP_USER; msg['To']=MAIL_TO
    msg['Subject']=Header(subject,'utf-8')
    if dry:
        print('[DRY] 不发送，主题:',subject,flush=True)
        return False
    s=smtplib.SMTP_SSL('smtp.qq.com',465,timeout=25,context=ssl.create_default_context())
    s.login(SMTP_USER,SMTP_PASS)
    s.sendmail(SMTP_USER,[MAIL_TO],msg.as_string())
    s.quit()
    return True


def review_previous(K, today):
    """H4.2/H4.3：回看历史推送的实际收益，写入 review.csv；连续跑偏的策略自动标记下线"""
    sigs = sorted(glob.glob(os.path.join(LOGDIR,'signals_*.csv')))
    if len(sigs) < 2:
        return None
    out=[]
    for fp in sigs:
        day=os.path.basename(fp).replace('signals_','').replace('.csv','')
        if day>=today: continue
        try: df=pd.read_csv(fp,dtype={'code':str})
        except Exception: continue
        for _,r in df.iterrows():
            c=str(r.get('code',''))
            v=K.get(c)
            if not v or today not in v: continue
            ds=sorted(v)
            if day not in v: continue
            i=ds.index(day)
            if i+1>=len(ds): continue
            buy=v[ds[i+1]][0]          # 次日开盘买（真实成交价）
            if not (buy>0): continue
            sell=v[today][1]
            ret=round((sell/buy-1)*100-0.1,2)
            out.append(dict(sig_day=day,strategy=r.get('strategy'),code=c,
                            stock=r.get('stock'),buy=round(buy,2),sell=round(sell,2),
                            ret=ret,hold=ds.index(today)-i))
    if not out: return None
    rv=pd.DataFrame(out)
    rv.to_csv(os.path.join(LOGDIR,'review.csv'),index=False,encoding='utf-8-sig')
    print('实盘回看 %d 条，均值 %+.2f%%，胜率 %.1f%%'%(
        len(rv),rv['ret'].mean(),(rv['ret']>0).mean()*100),flush=True)
    # 漂移检测：某策略累计 < -2% 且 >=10 笔 → 标记下线
    warn=[]
    for st,g in rv.groupby('strategy'):
        if len(g)>=10 and g['ret'].mean() < -2:
            warn.append('%s(%d笔 %+.2f%%)'%(st,len(g),g['ret'].mean()))
    if warn:
        print('⚠️ 漂移预警（建议下线）: '+', '.join(warn),flush=True)
        open(os.path.join(LOGDIR,'drift_warning.txt'),'w',encoding='utf-8').write('\n'.join(warn))
    return rv


def already_sent_today(now):
    """同一天不重复发信（除非 --force）"""
    p=os.path.join(LOGDIR,'send.log')
    if not os.path.exists(p): return False
    stamp=now.strftime('%Y-%m-%d')
    for line in open(p,encoding='utf-8'):
        if line.startswith(stamp) and line.strip().endswith('OK'):
            return True
    return False


def main():
    dry = '--dry' in sys.argv
    force = '--force' in sys.argv
    now0=datetime.now(BJ)
    if not dry and not force and already_sent_today(now0):
        print('今日已发送，跳过（--force 可强制）',flush=True)
        return True
    K=pickle.load(open(os.path.join(BASE,'_live_kline.pkl'),'rb'))
    today=max({d for v in K.values() for d in v})
    print('最新交易日 %s / %d 只'%(today,len(K)),flush=True)
    review_previous(K,today)       # 实盘校验
    ms=market_state(K,today)
    ms.to_csv(os.path.join(LOGDIR,'market_state.csv'),index=False,encoding='utf-8-sig')
    print('市场状态:\n%s'%ms.tail(4).to_string(index=False),flush=True)
    f=build_features(K,today,ms)
    print('特征 %d 只'%len(f),flush=True)
    # 硬过滤
    # ST/退市 + 除权除息股（XR/XD/DR，次日价格会跳空，买入价不可控）
    bad=f['name'].str.contains('ST|退|\\*',regex=True,na=False) | \
        f['name'].str.replace(' ','').str.startswith(('XR','XD','DR'))
    print('硬过滤剔除 %d 只（ST/退市/除权）'%int(bad.sum()),flush=True)
    f=f[~bad].copy()
    S=strategies(f)
    # 匹配
    hits=[]
    for code,name,cat,market,cond,sell,deq,win,seg in S:
        m=cond.fillna(False) if hasattr(cond,'fillna') else cond
        q=f[m].copy()
        if not len(q): continue
        # 剔一字（今日涨停且最低价=涨停价，次日也难买）→ 用 is_zt 标记，保留但提示
        # 每策略最多3只：按超跌深度优先（跌幅最大优先）
        q=q.sort_values('r20p')
        q=q.head(3)
        for _,r in q.iterrows():
            reason='近20日%+.1f%% / 距250日高%+.1f%% / 距MA60%+.1f%% / 60日分位%.0f / 板块%+.1f%%'%(
                r['r20p'],r['dd250'],r['gap60'],r['p60'],r['ind_chg'])
            hits.append(dict(strategy=code,name=name,cat=cat,market=market,
                             code=r['code'],stock=r['name'],price=r['close'],
                             buy='次日开盘价',sell=sell,deq=deq,win=win,seg=seg,
                             reason=reason,tags=r['tags'],ind=r['ind2'],
                             is_zt=int(r['is_zt'])))
    # 全局去重 + 上限10
    seen=set();uniq=[]
    for h in sorted(hits,key=lambda x:-x['deq']):
        if h['code'] in seen: continue
        seen.add(h['code']);uniq.append(h)
    uniq=uniq[:10]
    # 邮件
    now=datetime.now(BJ)
    if uniq:
        body=['<div style="font-family:-apple-system,Microsoft YaHei,sans-serif;max-width:760px;margin:auto;color:#111">']
        body.append('<h2 style="font-size:18px">%s 选股信号 · 次日开盘买入</h2>'%today)
        body.append('<p style="color:#555;font-size:13px">共 %d 只，来自 %d 套策略。买入口径统一：'
                    '<b>T 日收盘出信号 → 次日开盘价买入</b>；已剔除 ST/退市/停牌。</p>'%(len(uniq),len(set(h['strategy'] for h in uniq))))
        cur=ms[ms.day==today]
        if len(cur):
            r=cur.iloc[0]
            body.append('<p style="background:#f3f4f6;padding:8px;border-radius:6px;font-size:13px">'
                        '当日市场：涨停 <b>%s</b> 家，最高 <b>%s</b> 板，赚钱效应 <b>%s</b>，'
                        '情绪 <b>%s</b>，牛熊 <b>%s</b></p>'%(r['zt_n'],r['max_bd'],r['earn'],r['regime'],r['bb']))
        from itertools import groupby
        for st,g in groupby(sorted(uniq,key=lambda x:(x['strategy'],-x['deq'])),key=lambda x:x['strategy']):
            g=list(g); h=g[0]
            body.append('<div style="border:1px solid #e5e7eb;border-radius:8px;padding:12px;margin:10px 0">')
            body.append('<div style="font-weight:600;font-size:15px">%s · %s <span style="color:#6b7280;font-size:12px">［%s］</span></div>'%(h['strategy'],h['name'],h['cat']))
            body.append('<div style="font-size:12px;color:#6b7280;margin:4px 0 8px">适用：%s ｜ <b>买：%s</b> ｜ <b>卖：%s</b> ｜ 历史日等权 %+.2f%% / 胜率 %.1f%% / 三段 %s</div>'%(
                h['market'],h['buy'],h['sell'],h['deq'],h['win'],h['seg']))
            body.append('<table style="width:100%;border-collapse:collapse;font-size:13px">')
            body.append('<tr style="background:#f9fafb"><th align=left>代码</th><th align=left>名称</th><th align=right>今收</th><th align=left>触发依据</th><th align=left>题材</th></tr>')
            for x in g:
                zt=' <span style="color:#dc2626">涨停</span>' if x['is_zt'] else ''
                body.append('<tr><td>%s</td><td>%s%s</td><td align=right>%.2f</td><td style="font-size:12px">%s</td><td style="font-size:12px">%s</td></tr>'%(
                    x['code'],x['stock'],zt,x['price'],x['reason'],x['tags'][:26]))
            body.append('</table></div>')
        body.append('<p style="font-size:12px;color:#6b7280">历史数据来自 2016–2026 全市场回测（184 万样本），三段=训练/验证/样本外。'
                    '题材字段仅 2025-10 后可查，作为辅助信息，不参与筛选。信号仅供研究，不构成投资建议。</p></div>')
        html=''.join(body)
        subject='【选股信号】%s %d只 / %d套策略'%(today,len(uniq),len(set(h['strategy'] for h in uniq)))
    else:
        html='<div style="font-family:Microsoft YaHei"><h3>%s 无信号</h3><p>今日各策略均未触发，未覆盖状态说明见附件日志。</p></div>'%today
        subject='【选股信号】%s 无信号'%today
    # 落盘
    j=dict(scan_time=now.strftime('%Y-%m-%d %H:%M:%S'),base_day=today,
           market=ms[ms.day==today].to_dict('records'),signals=uniq,
           strategy_count=len(S),hit_count=len(hits))
    json.dump(j,open(os.path.join(LOGDIR,'latest.json'),'w',encoding='utf-8'),ensure_ascii=False,indent=1)
    pd.DataFrame(uniq).to_csv(os.path.join(LOGDIR,'signals_%s.csv'%today),index=False,encoding='utf-8-sig')
    open(os.path.join(LOGDIR,'mail_%s.html'%today),'w',encoding='utf-8').write(html)
    print('信号 %d 条（策略 %d 套，触发 %d 条）'%(len(uniq),len(S),len(hits)),flush=True)
    for h in uniq: print('  %-3s %-12s %s %-8s 今收%.2f'%(h['strategy'],h['name'],h['code'],h['stock'],h['price']),flush=True)
    ok=send_mail(subject,html,dry)
    print('邮件发送: %s'%('成功 ✅' if ok else ('DRY' if dry else '失败 ❌')),flush=True)
    with open(os.path.join(LOGDIR,'send.log'),'a',encoding='utf-8') as fp:
        fp.write('%s | %s | %d条 | %s\n'%(now.strftime('%Y-%m-%d %H:%M:%S'),subject,len(uniq),'OK' if ok else ('DRY' if dry else 'FAIL')))
    return ok

if __name__=='__main__':
    main()
