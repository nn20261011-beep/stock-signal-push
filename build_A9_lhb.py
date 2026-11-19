# -*- coding: utf-8 -*-
"""A9 龙虎榜全历史：akshare.stock_lhb_detail_em 按年抓取"""
import os,time
import pandas as pd
import akshare as ak
BASE=os.path.dirname(os.path.abspath(__file__))
OUT=os.path.join(BASE,'_dataset'); os.makedirs(OUT,exist_ok=True)
YRS=[(2016,2016),(2017,2017),(2018,2018),(2019,2019),(2020,2020),
     (2021,2021),(2022,2022),(2023,2023),(2024,2024),(2025,2025),(2026,2026)]
all_df=[]; t0=time.time()
for y,y2 in YRS:
    a='%d0101'%y; b='%d1231'%(y if y<2026 else 2026)
    if y==2026: b='20261119'
    try:
        df=ak.stock_lhb_detail_em(start_date=a,end_date=b)
        all_df.append(df)
        print('  %d: %d 行  (累计 %.0f 分)'%(y,len(df),(time.time()-t0)/60),flush=True)
    except Exception as e:
        print('  %d: 失败 %s'%(y,str(e)[:80]),flush=True)
    time.sleep(1)
if all_df:
    D=pd.concat(all_df,ignore_index=True)
    D.to_parquet(os.path.join(OUT,'lhb.parquet'),index=False)
    print('')
    print('完成：%d 行 / %d 个上榜日 / %d 只票'%(
        len(D),D['上榜日'].nunique(),D['代码'].nunique()),flush=True)
    print('日期范围 %s ~ %s'%(D['上榜日'].min(),D['上榜日'].max()),flush=True)
    print('存 _dataset/lhb.parquet',flush=True)
else:
    print('全部失败')
