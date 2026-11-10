# -*- coding: utf-8 -*-
"""
盘中/盘前信号扫描器 —— 跑在 GitHub Actions 上，不依赖本机
数据源：腾讯行情（qt.gtimg.cn，免费无需 token）
输出：邮件 + 控制台

重要：本脚本的选股规则来自 site_plans.py 的 10 年回测结论，
      规则参数全部写死在 STRATEGIES 里，改参数需同步改回测脚本。
"""
import os
import sys
import json
import time
import smtplib
import urllib.request
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header

BJ = timezone(timedelta(hours=8))
INTRADAY = os.environ.get('INTRADAY', '') == '1'   # 盘中模式：不写状态库、不做收盘确认
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}


def now_bj():
    return datetime.now(BJ)


def http_get(url, encoding='gbk', timeout=15):
    req = urllib.request.Request(url, headers=UA)
    raw = urllib.request.urlopen(req, timeout=timeout).read()
    return raw.decode(encoding, errors='ignore')


def get_quotes(codes):
    """腾讯批量行情，返回 {code: {...}}"""
    out = {}
    B = 60
    for i in range(0, len(codes), B):
        chunk = codes[i:i + B]
        q = ','.join(('sh' if c.startswith(('6', '5')) else 'sz') + c for c in chunk)
        try:
            txt = http_get('https://qt.gtimg.cn/q=' + q)
        except Exception:
            continue
        for line in txt.split(';'):
            line = line.strip()
            if not line or '=' not in line:
                continue
            body = line.split('=', 1)[1].strip('"')
            f = body.split('~')
            if len(f) < 40:
                continue
            try:
                out[f[2]] = {
                    'code': f[2], 'name': f[1],
                    'price': float(f[3] or 0),
                    'prev': float(f[4] or 0),
                    'open': float(f[5] or 0),
                    'vol': float(f[6] or 0),          # 手
                    'high': float(f[33] or 0),
                    'low': float(f[34] or 0),
                    'amount': float(f[37] or 0) * 1e4,  # 元
                    'turnover': float(f[38] or 0),
                    'pct': float(f[32] or 0),
                    'amount_ratio': float(f[49] or 0) if len(f) > 49 else 0,
                }
            except Exception:
                continue
    return out


def get_kline_day(code, count=80):
    """日线（前复权）。主源东财 push2his，备源新浪。返回 [(date, open, close, high, low, vol), ...]"""
    # ---- 主源：东财 push2his ----
    secid = ('1.' if code.startswith(('6', '5')) else '0.') + code
    url = ('https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=%s'
           '&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57'
           '&klt=101&fqt=1&end=20500101&lmt=%d' % (secid, count))
    try:
        txt = http_get(url, encoding='utf-8', timeout=12)
        j = json.loads(txt)
        kl = ((j.get('data') or {}).get('klines') or [])
        out = []
        for line in kl:
            f = line.split(',')
            if len(f) < 7:
                continue
            out.append((f[0], float(f[1]), float(f[2]), float(f[3]), float(f[4]), float(f[5])))
        if len(out) >= 25:
            return out
    except Exception:
        pass

    # ---- 备源：新浪（不复权）----
    prefix = 'sh' if code.startswith(('6', '5')) else 'sz'
    url2 = ('https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketData.getKLineData'
            '?symbol=%s%s&scale=240&ma=no&datalen=%d' % (prefix, code, count))
    try:
        txt = http_get(url2, encoding='utf-8', timeout=12)
        arr = json.loads(txt)
        out = []
        for x in arr:
            out.append((str(x['day'])[:10], float(x['open']), float(x['close']),
                        float(x['high']), float(x['low']), float(x['volume']) / 100.0))
        return out
    except Exception:
        return []


def calc_metrics(bars):
    """复刻 playbook.js 的 metrics()"""
    if not bars or len(bars) < 25:
        return None
    i = len(bars) - 1
    o, c, h, l, v = bars[i][1], bars[i][2], bars[i][3], bars[i][4], bars[i][5]
    pc = bars[i - 1][2]
    if pc <= 0:
        return None
    chg = (c - pc) / pc * 100
    openGap = (o - pc) / pc * 100
    v5 = sum(bars[k][5] for k in range(i - 5, i)) / 5
    vr = v / v5 if v5 > 0 else 0

    def ma(nn):
        if i - nn + 1 < 0:
            return None
        return sum(bars[q][2] for q in range(i - nn + 1, i + 1)) / nn

    ma5, ma10, ma20 = ma(5), ma(10), ma(20)
    trendUp = bool(ma5 and ma10 and ma20 and ma5 > ma10 > ma20)
    r20 = (c / bars[i - 20][2] - 1) * 100 if i >= 20 and bars[i - 20][2] > 0 else 0

    win = [x[2] for x in bars[max(0, i - 59):i + 1]]
    p60 = (sum(1 for x in win if x < c) / len(win) * 100) if len(win) >= 10 else None

    look = min(250, i + 1)
    hi250 = max(x[3] for x in bars[i - look + 1:i + 1])
    dd250 = (c / hi250 - 1) * 100 if hi250 > 0 else 0
    back = min(120, i)
    ret120 = (c / bars[i - back][2] - 1) * 100 if back > 0 and bars[i - back][2] > 0 else 0

    # 箱体
    boxAmp = boxHigh = boxLow = None
    if i >= 60:
        best = -1e9
        for bw in range(20, min(60, i - 59) + 1):
            bs = i - bw + 1
            bh = max(x[3] for x in bars[bs:i + 1])
            bl = min(x[4] for x in bars[bs:i + 1])
            if bl <= 0:
                continue
            amp = (bh - bl) / bl * 100
            if amp > 35:
                continue
            bv = sum(x[5] for x in bars[bs:i + 1]) / bw
            pv_arr = [x[5] for x in bars[max(0, bs - 60):bs]]
            if len(pv_arr) < 20:
                continue
            pv = sum(pv_arr) / len(pv_arr)
            vm = bv / pv if pv > 0 else 0
            if vm < 1.10:
                continue
            sc = -amp + vm * 5
            if sc > best:
                best = sc
                boxAmp, boxHigh, boxLow = round(amp, 1), round(bh, 2), round(bl, 2)

    upper = h - max(o, c)
    body = abs(c - o)

    # 布林/CCI
    bollPos = cci = None
    if i >= 21:
        arr = [x[2] for x in bars[i - 19:i + 1]]
        bMid = sum(arr) / 20
        bSd = (sum((x - bMid) ** 2 for x in arr) / 20) ** 0.5
        bUp, bLow = bMid + 2 * bSd, bMid - 2 * bSd
        bW = bUp - bLow
        bollPos = (c - bLow) / bW if bW > 0 else 0.5
    if i >= 15:
        tps = [(x[3] + x[4] + x[2]) / 3 for x in bars[i - 13:i + 1]]
        cMa = sum(tps) / len(tps)
        cMd = sum(abs(x - cMa) for x in tps) / len(tps)
        cci = (tps[-1] - cMa) / (0.015 * cMd) if cMd > 0 else 0

    # 搓揉线
    rub = False
    if i >= 61:
        p1 = bars[i - 1]
        o1, c1, h1, l1, v1 = p1[1], p1[2], p1[3], p1[4], p1[5]
        up1 = h1 - max(o1, c1)
        dn2 = min(o, c) - l
        bd1, bd2 = abs(c1 - o1), abs(c - o)
        rng1, rng2 = h1 - l1, h - l
        if rng1 > 0 and rng2 > 0:
            rub = (up1 / rng1 >= 0.5 and dn2 / rng2 >= 0.5
                   and (bd1 == 0 or up1 >= bd1 * 2)
                   and (bd2 == 0 or dn2 >= bd2 * 2)
                   and v < v1)

    closePos = (c - l) / (h - l) if h > l else 0.5

    _prev_zt = False
    if i >= 2 and bars[i - 2][2] > 0:
        _prev_zt = (bars[i - 1][2] / bars[i - 2][2] - 1) * 100 >= 9.5
    return {
        'prev_zt': bool(_prev_zt),
        'is_zt': bool(chg >= 9.5),
        'close': c, 'chg': round(chg, 2), 'openGap': round(openGap, 2), 'vr': round(vr, 2),
        'ma10': ma10, 'ma20': ma20, 'trendUp': trendUp, 'r20': round(r20, 2),
        'p60': p60, 'dd250': round(dd250, 1), 'ret120': round(ret120, 1),
        'boxAmp': boxAmp, 'boxHigh': boxHigh, 'boxLow': boxLow,
        'upper': upper, 'body': body, 'rub': rub,
        'bollPos': bollPos, 'cci': cci, 'belowMa20': (c < ma20) if ma20 else None,
        'closePos': round(closePos, 3),
        'gap_ma20': round((c - ma20) / ma20 * 100, 2) if ma20 else None,
    }


def match(plan_id, m):
    """复刻 playbook.js 的 match()"""
    if not m:
        return None
    if plan_id == 'gold_core':
        if not (m['ma10'] and m['ma20']) or m['ma10'] <= m['ma20']:
            return None
        g = m['gap_ma20']
        if g is None or g < 0 or g > 3:
            return None
        if not (1.2 <= m['vr'] < 1.5):
            return None
        if not (3 <= m['chg'] <= 7):
            return None
        return '多头回踩MA20 内%.1f%% + 量比%.2f + 涨%.2f%%' % (g, m['vr'], m['chg'])

    if plan_id == 'x3_volume':
        p60 = m['p60'] if m['p60'] is not None else 50
        if m['vr'] < 2 or m['chg'] <= 0 or p60 >= 40:
            return None
        return '量比%.2f× + 收涨%.2f%% + 分位%.0f%%' % (m['vr'], m['chg'], p60)

    if plan_id == 'x369':
        if m['chg'] < 3 or m['vr'] < 1.5 or m['closePos'] < 0.8:
            return None
        if m['boxAmp'] is not None and m['boxAmp'] > 25:
            return None
        return '涨%.2f%% + 量比%.2f + 收盘位置%.2f' % (m['chg'], m['vr'], m['closePos'])

    if plan_id == 'duck_head':
        if not (m['ma10'] and m['ma20']) or m['ma10'] <= m['ma20']:
            return None
        d = abs(m['close'] - m['ma20']) / m['ma20'] * 100
        if d > 3 or m['vr'] < 1.2:
            return None
        return 'MA10>MA20 + 回踩MA20 %.1f%%内 + 量比%.2f' % (d, m['vr'])

    if plan_id == 'yj_pick':
        if m['chg'] >= 9.5 and m['trendUp'] and m['r20'] > 15:
            return '涨停+多头+20日%.1f%%' % m['r20']
        return None

    if plan_id == 'jkb_pick':
        if m['chg'] >= 5 and m['trendUp'] and m['r20'] > 10 and m['vr'] >= 1.5:
            return '强涨%.2f%%+多头+20日%.1f%%+放量' % (m['chg'], m['r20'])
        return None

    if plan_id == 'limit_up':
        if m['chg'] >= 9.5:
            return '封涨停 %.2f%%' % m['chg']
        return None

    if plan_id == 'chaoxiao':
        if not (m['dd250'] <= -38 and m['ret120'] <= -8):
            return None
        if m['boxAmp'] is None:
            return None
        if m['chg'] < 3 or m['vr'] < 1.5:
            return None
        if not (m['body'] > 0 and m['upper'] >= m['body'] * 0.6):
            return None
        if m['close'] < m['boxHigh'] * 0.85:
            return None
        return '腰斩%.0f%%+阴半年%.0f%%+箱体(%.2f~%.2f)+放量%.1f×+长上影' % (
            m['dd250'], m['ret120'], m['boxLow'], m['boxHigh'], m['vr'])

    if plan_id == 'deep_v':
        if m['bollPos'] is None or m['cci'] is None:
            return None
        if m['bollPos'] >= 0.2 or m['cci'] >= -100 or not m['belowMa20']:
            return None
        if m['p60'] is not None and m['p60'] >= 40:
            return None
        return '布林下轨%.2f + CCI%.0f + 跌破MA20' % (m['bollPos'], m['cci'])

    if plan_id == 'rub_line':
        if not m['rub']:
            return None
        p60 = m['p60'] if m['p60'] is not None else 50
        if p60 >= 40:
            return None
        return '搓揉线洗盘 + 分位%.0f%%' % p60

    # ---- 自建打法（10年验证：低位涨停 T+5 +3.28%/58.2%，11年8正）----
    if plan_id == 'low_limit':
        # 昨日涨停 + 距250日高点<-50% + 60日分位<30
        if not m.get('prev_zt'):
            return None
        if m['dd250'] > -50:
            return None
        p60 = m['p60'] if m['p60'] is not None else 50
        if p60 >= 30:
            return None
        return '昨涨停+距250日高%.0f%%+分位%.0f%%（低位接力）' % (m['dd250'], p60)

    if plan_id == 'oversold':
        # 近20日跌幅<-20% + 今日收阳 + 量比>1.2 + 非涨停 + 距250日高<-30%
        if m.get('is_zt') or m['chg'] <= 0:
            return None
        if m['r20'] > -20:
            return None
        if m['vr'] <= 1.2:
            return None
        if m['dd250'] > -30:
            return None
        return '20日跌%.0f%%+今日收涨%.2f%%+量比%.2f（超跌反弹）' % (m['r20'], m['chg'], m['vr'])

    return None


PLAN_NAMES = {
    'gold_core': 'GOLD核心', 'x3_volume': '三倍量', 'x369': '369吃货',
    'duck_head': '老鸭头', 'yj_pick': '养家龙头', 'jkb_pick': '科比主流',
    'limit_up': '打板', 'chaoxiao': '炒小炒差', 'deep_v': '深V反转',
    'dip_buy': '错杀低吸', 'rub_line': '搓揉线',
    'low_limit': '低位涨停', 'oversold': '超跌反弹',
}

# 每个战法的建议持有天数（来自回测）
PLAN_HOLD = {
    'gold_core': 5, 'x3_volume': 5, 'x369': 5, 'duck_head': 5,
    'yj_pick': 3, 'jkb_pick': 3, 'limit_up': 1, 'chaoxiao': 5,
    'deep_v': 5, 'dip_buy': 2, 'rub_line': 5,
    'low_limit': 5, 'oversold': 5,
}


def push_github_issue(title, body):
    """有信号时创建 GitHub Issue —— GitHub 会自动推送通知到手机 App / 邮箱"""
    tk = os.environ.get('GH_TOKEN', '')
    repo = os.environ.get('GH_REPO', '')
    if not tk or not repo:
        return False
    try:
        data = json.dumps({'title': title, 'body': body}).encode('utf-8')
        req = urllib.request.Request(
            'https://api.github.com/repos/%s/issues' % repo, data=data,
            headers={'Authorization': 'token ' + tk, 'Accept': 'application/vnd.github+json',
                     'Content-Type': 'application/json', 'User-Agent': 'signal-bot'})
        r = json.loads(urllib.request.urlopen(req, timeout=20).read().decode('utf-8'))
        print('[OK] Issue 已创建 #%s' % r.get('number'))
        return True
    except Exception as e:
        print('[WARN] 创建 Issue 失败: %s' % e)
        return False


def load_sent():
    p = os.path.join('docs', 'sent_today.json')
    if not os.path.exists(p):
        return {}
    try:
        d = json.load(open(p, encoding='utf-8'))
        return d if d.get('day') == now_bj().strftime('%Y-%m-%d') else {}
    except Exception:
        return {}


def save_sent(sent):
    os.makedirs('docs', exist_ok=True)
    json.dump(sent, open(os.path.join('docs', 'sent_today.json'), 'w', encoding='utf-8'),
              ensure_ascii=False)


def send_mail(subject, html, to_addr):
    user = os.environ.get('SMTP_USER', '')
    pw = os.environ.get('SMTP_PASS', '')
    host = os.environ.get('SMTP_HOST', 'smtp.qq.com')
    if not user or not pw:
        print('[WARN] 未配置 SMTP_USER / SMTP_PASS，跳过发信')
        return False
    msg = MIMEMultipart()
    msg['From'] = Header('A股信号 %s' % user, 'utf-8')
    msg['To'] = Header(to_addr, 'utf-8')
    msg['Subject'] = Header(subject, 'utf-8')
    msg.attach(MIMEText(html, 'html', 'utf-8'))
    try:
        s = smtplib.SMTP_SSL(host, 465, timeout=20)
        s.login(user, pw)
        s.sendmail(user, [to_addr], msg.as_string())
        s.quit()
        print('[OK] 邮件已发 %s' % to_addr)
        return True
    except Exception as e:
        print('[ERR] 发信失败 %s' % e)
        return False


def get_universe():
    """取候选股：全市场主板。东财 clist 每页上限 100，需分页（共约 56 页）"""
    codes = []
    seen = set()
    page = 1
    while page <= 70:
        url = ('https://push2.eastmoney.com/api/qt/clist/get?pn=%d&pz=100&po=1&np=1'
               '&fltt=2&invt=2&fid=f3&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23'
               '&fields=f12,f14' % page)
        try:
            req = urllib.request.Request(url, headers=UA)
            j = json.loads(urllib.request.urlopen(req, timeout=20).read().decode('utf-8'))
            d = j.get('data') or {}
            items = d.get('diff') or []
            if not items:
                break
            for x in items:
                c = str(x.get('f12', ''))
                if len(c) == 6 and (c.startswith('60') or c.startswith('00')) \
                        and not c.startswith('688') and c not in seen:
                    seen.add(c)
                    codes.append(c)
            total = d.get('total') or 0
            if page * 100 >= total:
                break
            page += 1
            time.sleep(0.15)
        except Exception as e:
            print('[WARN] 第 %d 页失败: %s' % (page, e))
            page += 1
            time.sleep(0.5)
    return codes


import state as ST

# 各战法在什么状态下有效（来自 library11.py 10年回测）
PLAN_GATE = {
    # 每个「情绪基调」配最合适的战法（按 10 年回测 T+5 排序，样本>=1000）
    # 数据源：library11.py 405 个状态格子 + build_pools8.py 自建打法
    '冰点期': {
        'oversold':  'T+5 +6.19%/胜率70.6%（冰点期×熊市，1204笔，11年9正）',
        'dip_buy':   'T+5 +2.98%/胜率62.3%（15710笔，12年8正）',
        'x3_volume': 'T+5 +2.68%/胜率58.0%（1917笔，12年8正）',
        'deep_v':    'T+5 +1.47%/胜率57.9%（60893笔，12年8正）',
    },
    '高潮期': {
        'low_limit': 'T+5 +5.22%/胜率63.2%（最高标低位接力，1247笔，11年9正）',
    },
    '发酵期': {
        'oversold':  'T+5 +4.41%/胜率62.5%（发酵期×熊市，3969笔，11年10正）',
    },
    '分化期': {
        'dip_buy':   'T+5 +1.38%/胜率53.8%（26042笔，12年8正）',
    },
    '低迷期': {
        'x3_volume': 'T+5 +0.69%/胜率51.5%（7146笔，12年9正）',
    },
}

PLAN_BLOCK = {'yj_pick', 'jkb_pick', 'limit_up', 'x369'}


def main():
    t0 = time.time()
    print('=== 扫描开始 %s ===' % now_bj().strftime('%Y-%m-%d %H:%M:%S'))

    codes = get_universe()
    print('候选 %d 只' % len(codes))
    if not codes:
        print('无候选，退出')
        return

    quotes = get_quotes(codes)
    print('行情 %d 只' % len(quotes))

    # 只对「涨幅>3% 或 量比>1.5」的票算 K 线（控制请求量）
    cand_set = set(c for c, q in quotes.items()
                   if q['pct'] >= 3 or q['amount_ratio'] >= 1.5 or q['pct'] <= -3)
    # 低位涨停打法需要「昨日涨停」的票 —— 把它们也加进候选
    try:
        for c in ST.load_zt_prev():
            if c in quotes:
                cand_set.add(c)
    except Exception:
        pass
    cand = list(cand_set)
    print('需要算K线 %d 只（含昨日涨停股）' % len(cand))

    # ---- 市场状态判定 ----
    today_str0 = now_bj().strftime('%Y-%m-%d')
    st_rows = [r for r in ST.load_state() if r['day'] < today_str0]
    regime = 'NA'
    if len(st_rows) >= 1:
        regime = ST.calc_regime(st_rows[-1])
    print('前一日(%s) max_bd=%s earn=%s → 今日 regime=%s' % (
        st_rows[-1]['day'] if st_rows else '-',
        st_rows[-1]['max_bd'] if st_rows else '-',
        st_rows[-1]['earn'] if st_rows else '-', regime))

    # 今日允许使用的战法
    allowed = set()
    today_gate = PLAN_GATE.get(regime, {})
    for pid, note in today_gate.items():
        allowed.add(pid)
        print('  ✅ 允许 %-8s（%s）' % (PLAN_NAMES.get(pid, pid), note))
    if not allowed:
        print('  ⛔ 今日状态下无战法达标 → 建议空仓')

    hits = []

    def work(code):
        out = []
        bars = get_kline_day(code, 80)
        if len(bars) < 25:
            return out
        m = calc_metrics(bars)
        if not m:
            return out
        q = quotes.get(code)
        if not q:
            return out
        for pid in PLAN_NAMES:
            if pid not in allowed:
                continue
            reason = match(pid, m)
            if reason:
                out.append({
                    'code': code, 'name': q['name'], 'price': q['price'],
                    'pct': q['pct'], 'plan': pid, 'plan_name': PLAN_NAMES[pid],
                    'reason': reason, 'hold': PLAN_HOLD[pid],
                })
        return out

    from concurrent.futures import ThreadPoolExecutor, as_completed
    done_n = 0
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = [ex.submit(work, c) for c in cand]
        for fu in as_completed(futs):
            done_n += 1
            if done_n % 100 == 0:
                print('  进度 %d/%d' % (done_n, len(cand)), flush=True)
            try:
                hits.extend(fu.result())
            except Exception:
                continue

    print('命中 %d 条' % len(hits))
    print('耗时 %.1f 秒' % (time.time() - t0))

    # 生成邮件
    now = now_bj().strftime('%Y-%m-%d %H:%M')
    if not hits:
        subject = '📭 %s 无信号' % now
        html = '<div style="font-family:Microsoft YaHei,sans-serif;font-size:14px">' \
               '<h3>今日无信号</h3><p>扫描 %d 只，没有战法触发。</p></div>' % len(codes)
    else:
        hits.sort(key=lambda x: (-x['pct']))
        subject = '🎯 %s 命中 %d 只' % (now, len(hits))
        rows = ''
        for h in hits:
            color = '#e11d48' if h['pct'] >= 0 else '#059669'
            rows += ('<tr>'
                     '<td style="padding:6px 8px;border:1px solid #e5e7eb"><b>%s</b><br>'
                     '<span style="color:#9ca3af;font-size:11px">%s</span></td>'
                     '<td style="padding:6px 8px;border:1px solid #e5e7eb;text-align:right">%.2f</td>'
                     '<td style="padding:6px 8px;border:1px solid #e5e7eb;text-align:right;color:%s;font-weight:600">%+.2f%%</td>'
                     '<td style="padding:6px 8px;border:1px solid #e5e7eb">%s</td>'
                     '<td style="padding:6px 8px;border:1px solid #e5e7eb;font-size:12px">%s</td>'
                     '<td style="padding:6px 8px;border:1px solid #e5e7eb;text-align:center">%d 日</td>'
                     '</tr>') % (h['name'], h['code'], h['price'], color, h['pct'],
                                 h['plan_name'], h['reason'], h['hold'])
        html = ('<div style="font-family:Microsoft YaHei,sans-serif;font-size:13px;color:#111827">'
                '<h3 style="margin:0 0 8px">🎯 战法命中 %d 只 · %s</h3>'
                '<table style="border-collapse:collapse;width:100%%;max-width:900px">'
                '<thead><tr style="background:#f3f4f6">'
                '<th style="padding:6px 8px;border:1px solid #e5e7eb">股票</th>'
                '<th style="padding:6px 8px;border:1px solid #e5e7eb">现价</th>'
                '<th style="padding:6px 8px;border:1px solid #e5e7eb">涨幅</th>'
                '<th style="padding:6px 8px;border:1px solid #e5e7eb">战法</th>'
                '<th style="padding:6px 8px;border:1px solid #e5e7eb">触发原因</th>'
                '<th style="padding:6px 8px;border:1px solid #e5e7eb">建议持有</th>'
                '</tr></thead><tbody>%s</tbody></table>'
                '<div style="color:#9ca3af;font-size:11px;margin-top:10px">'
                '规则来自持仓网站 playbook.js · 10年回测验证 · 次日开盘买入' 
                '</div></div>') % (len(hits), now, rows)

    # ---- 追加今日状态到历史库（盘中模式跳过，避免用未收盘数据污染）----
    if not INTRADAY:
      try:
        zt_prev_codes = ST.load_zt_prev()
        # 算涨停股的连板数（查 K 线）
        zt_codes_today = [c for c, q in quotes.items() if q['pct'] >= 9.8]
        zt_bd = {}
        for c in zt_codes_today[:120]:
            bb = get_kline_day(c, 12)
            k = 0
            for row in reversed(bb):
                prev_i = bb.index(row) - 1
                if prev_i < 0:
                    break
                pc = bb[prev_i][2]
                if pc > 0 and row[2] >= round(pc * 1.10, 2) - 0.011:
                    k += 1
                else:
                    break
            zt_bd[c] = max(k, 1)
        m_today = ST.compute_today_metrics(quotes, zt_prev_codes, zt_bd)
        today_str = now_bj().strftime('%Y-%m-%d')
        n_rows = ST.append_state(today_str, m_today)
        ST.save_zt_prev(m_today['zt_codes'])
        print('[OK] 状态库已更新到 %s（共 %d 行），今日涨停 %d 家、跌停 %d 家、最高 %d 板' % (
            today_str, n_rows, m_today['zt_n'], m_today['dt_n'], m_today['max_bd']))
        print('     明日 regime 预判 = %s' % ST.calc_regime({
            'max_bd': m_today['max_bd'], 'earn': m_today['earn']}))
      except Exception as e:
        print('[WARN] 更新状态库失败: %s' % e)

    # ---- 推送：只推新信号（当天已推过的不重复）----
    sent = load_sent()
    if sent.get('day') != now_bj().strftime('%Y-%m-%d'):
        sent = {'day': now_bj().strftime('%Y-%m-%d'), 'keys': []}
    sent_keys = set(sent.get('keys', []))
    fresh = [h for h in hits if (h['code'] + '|' + h['plan']) not in sent_keys]
    if fresh:
        lines = []
        for h in fresh:
            lines.append('- **%s**（%s）%.2f元 %+.2f%% · %s · 建议持%d日\n  - %s' % (
                h['name'], h['code'], h['price'], h['pct'],
                h['plan_name'], h['hold'], h['reason']))
        title = '🎯 %s 信号 %d 只（%s）' % (now_bj().strftime('%m-%d %H:%M'), len(fresh), regime)
        body = ('**市场状态**：%s\n\n**命中**：\n%s\n\n'
                '> 规则来自 10 年回测，历史胜率见下表。不是投资建议。' % (regime, '\n'.join(lines)))
        push_github_issue(title, body)
        for h in fresh:
            sent_keys.add(h['code'] + '|' + h['plan'])
        sent['keys'] = sorted(sent_keys)
        save_sent(sent)
        print('[OK] 新信号 %d 条已推送' % len(fresh))
    else:
        print('[OK] 无新信号（当天已推 %d 条）' % len(sent_keys))

    # 写 HTML 页面（GitHub Pages 可直接访问）
    try:
        os.makedirs('docs', exist_ok=True)
        with open('docs/index.html', 'w', encoding='utf-8') as f:
            f.write('<!DOCTYPE html><html><head><meta charset="utf-8">'
                    '<meta name="viewport" content="width=device-width,initial-scale=1">'
                    '<title>A股战法信号</title><style>'
                    'body{font-family:-apple-system,"Microsoft YaHei",sans-serif;margin:0;padding:16px;background:#f9fafb;color:#111827}'
                    '.card{background:#fff;border-radius:10px;padding:16px;box-shadow:0 1px 3px rgba(0,0,0,.1);max-width:900px;margin:0 auto}'
                    'table{border-collapse:collapse;width:100%;font-size:13px}'
                    'th,td{padding:8px;border-bottom:1px solid #e5e7eb;text-align:left}'
                    'th{background:#f3f4f6;font-weight:600}'
                    '.up{color:#e11d48;font-weight:600}.down{color:#059669;font-weight:600}'
                    '</style></head><body><div class="card">'
                    + html +
                    '</div></body></html>')
        print('[OK] docs/index.html 已写')
    except Exception as e:
        print('[WARN] 写 HTML 失败: %s' % e)

    # 写 JSON 快照
    try:
        os.makedirs('docs', exist_ok=True)
        with open('docs/latest.json', 'w', encoding='utf-8') as f:
            json.dump({'time': now, 'count': len(hits), 'hits': hits}, f, ensure_ascii=False, indent=1)
    except Exception:
        pass

    to_addr = os.environ.get('ALERT_TO', os.environ.get('SMTP_USER', ''))
    if to_addr:
        send_mail(subject, html, to_addr)
    else:
        print('[WARN] 未配置 ALERT_TO，仅写页面不发信')

    print(json.dumps(hits, ensure_ascii=False, indent=1)[:2000])


if __name__ == '__main__':
    main()
