# -*- coding: utf-8 -*-
"""
auction_alert.py —— 集合竞价梯队数据邮件（纯数据，不做判断，不套战法）

标题：【竞价梯队 09:26】5板1 4板2 3板4 2板4 首板35
正文：① 指数表  ② 昨日涨停股按连板梯队分组

口径：
  竞价涨幅 = 今开 / 昨收 − 1
  量比昨日 = 今日竞价量 / 昨日全天成交量
  量比5日  = 今日竞价量 / 前 5 个交易日日均成交量
  题材内排名 = 该股在其主题材的昨日涨停股里按连板数排名（同板按竞价涨幅降序）

数据源：
  昨日涨停与连板：_hist.pkl.gz 逐只算连续涨停天数
  今开/竞价量：腾讯 qt.gtimg.cn f[5]/f[6]
  昨日量/前5日量：日线 volume
  题材：东财 push2 slist（本地 _concept.json 只覆盖 172 概念，仅作补充）
  指数：腾讯 sh000001/sz399001/sz399006 + hkHSI + usDJI/usIXIC；日经/KOSPI 用新浪 b_NKY/b_KOSPI

时间：cron 7:00/7:30/8:00 三点错峰启动，job 内自旋等到 9:25:05 取数，9:26 前发出。
"""
import os, sys, json, gzip, pickle, smtplib, ssl, time, urllib.request
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone, timedelta
from collections import Counter, defaultdict
from email.mime.text import MIMEText
from email.header import Header

BASE = os.path.dirname(os.path.abspath(__file__))
BJ = timezone(timedelta(hours=8))
LOG = os.path.join(BASE, '_push_logs')
os.makedirs(LOG, exist_ok=True)
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
UA_EM = {**UA, 'Referer': 'https://quote.eastmoney.com/'}
SMTP_USER = os.environ.get('SMTP_USER', 'h1533165068@qq.com')
SMTP_PASS = os.environ.get('SMTP_PASS', 'xfboalpjikugjfgg')
MAIL_TO = os.environ.get('MAIL_TO', 'h1533165068@qq.com')

SKIP = ['板块', '首亏', '预减', '预增', '高市净率', '破发', '昨日', '热股', '最近多板',
        '微利', 'ST', '重仓', '融资融券', '转债', '增持', '回购', '举牌', '低价', '连续亏损']
GENERIC = ['沪股通', '深股通', '标准普尔', '富时罗素', 'MSCI中国', '中证500', '中盘股', '小盘股',
           '大盘股', '中盘成长', '小盘成长', '大盘成长', '题材股', '高市盈率', '破增发价股', '破净股',
           '股权激励', '基金减仓', '基金增仓', 'QFII新进', '私募新进', '保险新进', '外资背景',
           '趋势股', '近期新高', '百日新高', '历史新高', '反转股', '价值股', '成长股',
           '消费风格', '科技风格', '央国企改革', 'AH股', 'AB股', '上证380', '深证100R', 'HS300_',
           'IPO受益', '中特估', '周期股', '百元股', '低价股', '超跌股', '股权分散',
           '业绩预降', '2026中报扭亏', '2026中报预减', '高成长股', '深成500', '标普500']


def zt_price(pc):
    return float((Decimal(str(pc)) * Decimal('1.10')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


def load_hist():
    with gzip.open(os.path.join(BASE, '_hist.pkl.gz'), 'rb') as f:
        return pickle.load(f)


def yesterday_limit_up(K):
    """返回 (昨日日期, [dict])，逐只算连续涨停天数"""
    days = sorted({d for v in K.values() for d in v})
    if not days:
        return None, []
    y = days[-1]
    out = []
    for c, v in K.items():
        if not c.startswith(('60', '00')) or c.startswith('688'):
            continue
        if y not in v:
            continue
        ds = sorted(v)
        i = ds.index(y)
        if i < 1:
            continue
        pc = v[y][1]
        if abs(pc - zt_price(v[ds[i - 1]][1])) > 0.005:
            continue
        bd = 0
        for j in range(i, max(i - 15, -1), -1):
            if j < 1:
                break
            if abs(v[ds[j]][1] - zt_price(v[ds[j - 1]][1])) < 0.005:
                bd += 1
            else:
                break
        out.append(dict(code=c, prev_close=pc, bd=bd, prev_vol=v[y][4],
                        v5=sum(v[x][4] for x in ds[max(0, i - 5):i]) / 5 if i >= 1 else 0))
    return y, out


def fetch_quotes(codes):
    """腾讯实时：f[5]今开、f[6]成交量(手)、f[4]昨收、f[1]名称"""
    out = {}
    for i in range(0, len(codes), 60):
        chunk = codes[i:i + 60]
        q = ','.join(('sh' if c.startswith('6') else 'sz') + c for c in chunk)
        for _ in range(3):
            try:
                txt = urllib.request.urlopen(urllib.request.Request(
                    'https://qt.gtimg.cn/q=' + q, headers=UA), timeout=12).read().decode('gbk', 'ignore')
                for ln in txt.split(';'):
                    if '~' not in ln:
                        continue
                    f = ln.split('=', 1)[1].strip('"').split('~')
                    if len(f) < 40 or not f[2]:
                        continue
                    try:
                        out[f[2]] = dict(name=f[1], open=float(f[5] or 0),
                                         vol=float(f[6] or 0), prev=float(f[4] or 0))
                    except Exception:
                        pass
                break
            except Exception:
                time.sleep(0.4)
    return out


def fetch_boards(codes):
    """东财板块归属；断连重试 3 次"""
    out = {}
    for c in codes:
        secid = ('1.' if c.startswith('6') else '0.') + c
        u = ('https://push2.eastmoney.com/api/qt/slist/get?spt=3&fltt=1&invt=2'
             '&fields=f12,f13,f14&secid=%s&pn=1&np=1&pz=40' % secid)
        got = []
        for _ in range(3):
            try:
                j = json.loads(urllib.request.urlopen(
                    urllib.request.Request(u, headers=UA_EM), timeout=12).read())
                got = [x['f14'] for x in ((j.get('data') or {}).get('diff') or [])
                       if isinstance(x, dict) and x.get('f14')
                       and not any(k in x['f14'] for k in SKIP)]
                break
            except Exception:
                time.sleep(0.3)
        out[c] = got
        time.sleep(0.06)
    return out


def fetch_indexes():
    out = []
    for q, kmap in [('sh000001,sz399001,sz399006',
                     {'000001': '上证', '399001': '深证成指', '399006': '创业板指'}),
                    ('hkHSI', {'HSI': '恒生'}),
                    ('usDJI,usIXIC', {'.DJI': '道琼斯', '.IXIC': '纳斯达克'})]:
        try:
            s = urllib.request.urlopen(urllib.request.Request(
                'https://qt.gtimg.cn/q=' + q, headers=UA), timeout=15).read().decode('gbk', 'ignore')
            for ln in s.split(';'):
                if '~' not in ln:
                    continue
                f = ln.split('=', 1)[1].strip('"\n').split('~')
                if len(f) > 32 and f[2] in kmap:
                    out.append((kmap[f[2]], f[3], f[32]))
        except Exception as e:
            print('指数失败', q, e, flush=True)
    try:
        s = urllib.request.urlopen(urllib.request.Request(
            'https://hq.sinajs.cn/list=b_NKY,b_KOSPI',
            headers={**UA, 'Referer': 'https://finance.sina.com.cn'}), timeout=15).read().decode('gbk', 'ignore')
        for ln in s.split('\n'):
            if '=' not in ln:
                continue
            key = ln.split('=')[0].replace('var hq_str_', '')
            v = ln.split('=', 1)[1].strip('";').split(',')
            if len(v) >= 4:
                out.append(('日经225' if key == 'b_NKY' else '韩国KOSPI', v[1], v[3]))
    except Exception as e:
        print('外围失败', e, flush=True)
    order = ['上证', '深证成指', '创业板指', '恒生', '日经225', '韩国KOSPI', '道琼斯', '纳斯达克']
    out.sort(key=lambda x: order.index(x[0]) if x[0] in order else 99)
    return out


def build(rows, idx):
    cnt = Counter(r['bd'] for r in rows)
    parts = ['%s%d' % ('首板' if b == 1 else '%d板' % b, cnt[b]) for b in sorted(cnt, reverse=True)]
    subj = '【竞价梯队 09:26】' + ' '.join(parts)

    body = ['<div style="font-family:Microsoft YaHei,sans-serif;max-width:1180px;color:#111">']
    body.append('<table style="border-collapse:collapse;font-size:13px;margin-bottom:16px;min-width:360px">'
                '<tr style="background:#f3f4f6"><th align=left style="padding:6px 14px">指数</th>'
                '<th align=right style="padding:6px 14px">点位</th>'
                '<th align=right style="padding:6px 14px">涨跌</th></tr>')
    for nm, px, chg in idx:
        try:
            c = float(chg)
        except Exception:
            c = 0.0
        color = '#c0392b' if c > 0 else ('#1e8449' if c < 0 else '#333')
        body.append('<tr><td style="padding:6px 14px;border-top:1px solid #eef0f2">%s</td>'
                    '<td align=right style="padding:6px 14px;border-top:1px solid #eef0f2">%s</td>'
                    '<td align=right style="padding:6px 14px;border-top:1px solid #eef0f2;color:%s">%+.2f%%</td></tr>'
                    % (nm, px, color, c))
    body.append('</table>')

    body.append('<table style="border-collapse:collapse;font-size:12.5px">')
    heads = ['梯队', '名称(代码)', '昨收', '今开', '竞价涨幅', '量比昨日', '量比5日',
             '题材', '题材昨日涨停数', '题材内排名']
    body.append('<tr style="background:#f3f4f6">' + ''.join(
        '<th align=%s style="padding:6px 9px;white-space:nowrap">%s</th>'
        % ('left' if h in ('梯队', '名称(代码)', '题材') else 'right', h) for h in heads) + '</tr>')
    last = None
    for r in rows:
        if last is not None and r['bd'] != last:
            body.append('<tr><td colspan=10 style="border-top:2px solid #d1d5db;padding:0"></td></tr>')
        last = r['bd']
        g = r['gapo']
        color = '#c0392b' if g > 0 else ('#1e8449' if g < 0 else '#333')
        body.append('<tr>'
                    '<td style="padding:5px 9px;border-top:1px solid #eef0f2">%s</td>'
                    '<td style="padding:5px 9px;border-top:1px solid #eef0f2"><b>%s(%s)</b></td>'
                    '<td align=right style="padding:5px 9px;border-top:1px solid #eef0f2">%.2f</td>'
                    '<td align=right style="padding:5px 9px;border-top:1px solid #eef0f2">%.2f</td>'
                    '<td align=right style="padding:5px 9px;border-top:1px solid #eef0f2;color:%s"><b>%+.2f%%</b></td>'
                    '<td align=right style="padding:5px 9px;border-top:1px solid #eef0f2">%s</td>'
                    '<td align=right style="padding:5px 9px;border-top:1px solid #eef0f2">%s</td>'
                    '<td style="padding:5px 9px;border-top:1px solid #eef0f2">%s</td>'
                    '<td align=right style="padding:5px 9px;border-top:1px solid #eef0f2">%d</td>'
                    '<td align=right style="padding:5px 9px;border-top:1px solid #eef0f2">%s</td></tr>' % (
                        '首板' if r['bd'] == 1 else '%d板' % r['bd'], r['name'], r['code'],
                        r['prev_close'], r['open'], color, g,
                        ('%.2f' % r['vr_prev']) if r.get('vr_prev') is not None else '—',
                        ('%.2f' % r['vr_5']) if r.get('vr_5') is not None else '—',
                        r['main_con'], r['con_zt_n'], r['con_rank']))
    body.append('</table></div>')
    return subj, ''.join(body)


def send(subject, html):
    msg = MIMEText(html, 'html', 'utf-8')
    msg['From'], msg['To'] = SMTP_USER, MAIL_TO
    msg['Subject'] = Header(subject, 'utf-8')
    s = smtplib.SMTP_SSL('smtp.qq.com', 465, timeout=25, context=ssl.create_default_context())
    s.login(SMTP_USER, SMTP_PASS)
    s.sendmail(SMTP_USER, [MAIL_TO], msg.as_string())
    s.quit()


def wait_until(hhmmss):
    while True:
        if datetime.now(BJ).strftime('%H%M%S') >= hhmmss:
            return
        time.sleep(5)


def main():
    dry = '--dry' in sys.argv
    force = '--force' in sys.argv
    if not force:
        if datetime.now(BJ).strftime('%H%M') > '0930':
            print('已过竞价窗口，退出', flush=True)
            return
        wait_until('092505')

    K = load_hist()
    yday, rows = yesterday_limit_up(K)
    print('昨日(%s)涨停 %d 只' % (yday, len(rows)), flush=True)
    if not rows:
        return

    Q = fetch_quotes([r['code'] for r in rows])
    B = fetch_boards([r['code'] for r in rows])
    print('实时 %d 只 / 板块 %d 只（有概念 %d）' % (
        len(Q), len(B), sum(1 for v in B.values() if v)), flush=True)

    out = []
    for r in rows:
        q = Q.get(r['code'])
        if not q or q['open'] <= 0 or r['prev_close'] <= 0:
            continue
        core = [x for x in B.get(r['code'], []) if x not in GENERIC]
        out.append(dict(code=r['code'], name=q['name'], prev_close=r['prev_close'],
                        open=q['open'], gapo=round((q['open'] / r['prev_close'] - 1) * 100, 2),
                        bd=r['bd'], auc_vol=q['vol'],
                        vr_prev=round(q['vol'] * 100 / r['prev_vol'], 3) if r['prev_vol'] > 0 else None,
                        vr_5=round(q['vol'] * 100 / r['v5'], 3) if r['v5'] > 0 else None,
                        core=core))
    if not out:
        print('无可用数据', flush=True)
        return

    for r in out:
        cnt = Counter()
        for x in out:
            for c in set(r['core']) & set(x['core']):
                cnt[c] += 1
        if cnt:
            r['main_con'], r['con_zt_n'] = cnt.most_common(1)[0]
        else:
            r['main_con'] = r['core'][0] if r['core'] else '—'
            r['con_zt_n'] = 0
    by = defaultdict(list)
    for r in out:
        by[r['main_con']].append(r)
    for con, lst in by.items():
        lst.sort(key=lambda x: (-x['bd'], -x['gapo']))
        for i, r in enumerate(lst, 1):
            r['con_rank'] = '%d/%d' % (i, len(lst))

    out.sort(key=lambda r: (-r['bd'], -r['gapo']))
    idx = fetch_indexes()
    subj, html = build(out, idx)
    print('标题:', subj, flush=True)

    if dry:
        print('[DRY]', subj, flush=True)
    else:
        send(subj, html)
        print('已发', subj, flush=True)
    with open(os.path.join(LOG, 'send.log'), 'a', encoding='utf-8') as f:
        f.write('%s | %s | %d只 | %s\n' % (datetime.now(BJ).strftime('%Y-%m-%d %H:%M:%S'),
                                           subj, len(out), 'DRY' if dry else 'OK'))


if __name__ == '__main__':
    main()
