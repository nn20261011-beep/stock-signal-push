# -*- coding: utf-8 -*-
"""
auction_confirm_v3.py —— 9:25 竞价结束后的执行确认（不新增标的、不推低开）

逻辑：读昨晚 push_v3.py 生成的 latest_v3.json 清单 → 9:25:40 抓这些票的实际开盘价
     → 标注「可按开盘价买 / 高开过多放弃」→ 9:28 前发信

硬闸门：只在 9:25:00~9:28:59 之间运行；早于则自旋等待，晚于直接退出不发。
      绝不在开盘后拿盘中价冒充竞价价。
"""
import os, sys, json, time, smtplib, ssl
import urllib.request
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.header import Header

BASE = os.path.dirname(os.path.abspath(__file__))
BJ = timezone(timedelta(hours=8))
LOG = os.path.join(BASE, '_push_logs')
os.makedirs(LOG, exist_ok=True)
SMTP_USER = os.environ.get('SMTP_USER', 'h1533165068@qq.com')
SMTP_PASS = os.environ.get('SMTP_PASS', 'xfboalpjikugjfgg')
MAIL_TO = os.environ.get('MAIL_TO', 'h1533165068@qq.com')
VERSION = 'v3.0 / 竞价执行确认'

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}


def get_quotes(codes):
    out = {}
    for i in range(0, len(codes), 60):
        chunk = codes[i:i + 60]
        q = ','.join(('sh' if c.startswith(('6', '5')) else 'sz') + c for c in chunk)
        for _ in range(3):
            try:
                u = 'https://qt.gtimg.cn/q=' + q
                req = urllib.request.Request(u, headers=UA)
                txt = urllib.request.urlopen(req, timeout=10).read().decode('gbk', errors='ignore')
                for line in txt.split(';'):
                    if '=' not in line:
                        continue
                    f = line.split('=', 1)[1].strip('"').split('~')
                    if len(f) < 40 or not f[2]:
                        continue
                    try:
                        out[f[2]] = dict(name=f[1], open=float(f[5] or 0),
                                         prev=float(f[4] or 0), price=float(f[3] or 0))
                    except Exception:
                        pass
                break
            except Exception:
                time.sleep(0.4)
    return out


def send(subject, html):
    msg = MIMEText(html, 'html', 'utf-8')
    msg['From'] = SMTP_USER
    msg['To'] = MAIL_TO
    msg['Subject'] = Header(subject, 'utf-8')
    s = smtplib.SMTP_SSL('smtp.qq.com', 465, timeout=25, context=ssl.create_default_context())
    s.login(SMTP_USER, SMTP_PASS)
    s.sendmail(SMTP_USER, [MAIL_TO], msg.as_string())
    s.quit()


def main():
    dry = '--dry' in sys.argv
    force = '--force' in sys.argv
    now = datetime.now(BJ)
    hm = now.hour * 100 + now.minute

    # ---- 硬闸门：只在 9:25~9:28 发 ----
    if not force:
        if hm > 928:
            print('当前 %s 已过 9:28，跳过（绝不发过期竞价信号）' % now.strftime('%H:%M:%S'), flush=True)
            with open(os.path.join(LOG, 'send.log'), 'a', encoding='utf-8') as f:
                f.write('%s | SKIP | 竞价确认超时 |\n' % now.strftime('%Y-%m-%d %H:%M:%S'))
            return
        if hm < 925:
            target = now.replace(hour=9, minute=25, second=40, microsecond=0)
            wait = (target - now).total_seconds()
            if wait > 3600:
                print('距 9:25 还有 %.0f 分钟，超出合理等待，跳过' % (wait / 60), flush=True)
                return
            print('自旋等待 %.0f 秒到 9:25:40' % wait, flush=True)
            time.sleep(max(0, wait))
            now = datetime.now(BJ)
        elif now.second < 38:
            time.sleep(max(0, 40 - now.second))
            now = datetime.now(BJ)
        if not (925 <= (now.hour * 100 + now.minute) <= 928):
            print('等待后不在窗口内，跳过', flush=True)
            return

    lp = os.path.join(LOG, 'latest_v3.json')
    prev = None
    if os.path.exists(lp):
        try:
            prev = json.load(open(lp, encoding='utf-8'))
        except Exception:
            prev = None
    if not prev:
        # 本机计划任务场景：清单在云端，从 GitHub raw 拉
        raw = ('https://raw.githubusercontent.com/nn20261011-beep/'
               'stock-signal-push/main/_push_logs/latest_v3.json')
        try:
            req = urllib.request.Request(raw, headers=UA)
            prev = json.loads(urllib.request.urlopen(req, timeout=12).read().decode('utf-8'))
            print('已从云端拉取昨晚清单', flush=True)
        except Exception as e:
            print('无昨晚清单（本地/云端均失败）：%s' % e, flush=True)
            return
    sigs = prev.get('signals') or []
    if not sigs:
        print('昨晚无信号，仅做竞价新挑', flush=True)

    # 去重：今天已发过则跳过（本地日志）
    sp = os.path.join(LOG, 'send.log')
    if not dry and not force and os.path.exists(sp):
        stamp = now.strftime('%Y-%m-%d')
        for line in open(sp, encoding='utf-8'):
            if line.startswith(stamp) and '竞价确认' in line and line.strip().endswith('OK'):
                print('今日已发过竞价确认，跳过', flush=True)
                return

    # 云端多触发点去重：用 GitHub Contents API 抢建当日锁文件，成功者才发信
    if not dry and not force:
        tok = os.environ.get('GH_TOKEN')
        if tok:
            import base64
            daykey = now.strftime('%Y%m%d')
            path = '_push_logs/sent_confirm_%s' % daykey
            url = ('https://api.github.com/repos/nn20261011-beep/'
                   'stock-signal-push/contents/' + path)
            data = json.dumps(dict(message='auction lock ' + daykey,
                                   content=base64.b64encode(b'1').decode(), branch='main')).encode()
            req = urllib.request.Request(url, data=data, method='PUT', headers=dict(
                UA, **{'Authorization': 'token ' + tok,
                       'Accept': 'application/vnd.github+json',
                       'Content-Type': 'application/json'}))
            try:
                resp = urllib.request.urlopen(req, timeout=15)
                print('抢到当日锁 %s (HTTP %s)' % (daykey, resp.status), flush=True)
            except Exception as e:
                code = getattr(e, 'code', None)
                print('未抢到锁(HTTP %s)，说明其它触发点已发，跳过' % code, flush=True)
                return

    # ---- 竞价后按身位新挑当日票（只在昨日涨停池里选，不接低开） ----
    fresh = []
    try:
        import gzip, pickle
        hp = os.path.join(BASE, '_hist.pkl.gz')
        if os.path.exists(hp):
            with gzip.open(hp, 'rb') as f:
                K = pickle.load(f)
            dlist = sorted({d for v in K.values() for d in v})
            if len(dlist) >= 2:
                t_prev = dlist[-1]      # 若在盘前跑，最新日=昨日
                t2 = dlist[-2]
                pool = {}
                for c, v in K.items():
                    if t_prev not in v or t2 not in v:
                        continue
                    pc = v[t2][1]
                    if pc <= 0:
                        continue
                    x = (v[t_prev][1] / pc - 1) * 100
                    if 9.8 <= x <= 10.6:
                        run = 1
                        j = dlist.index(t_prev) - 1
                        while j >= 1:
                            ds_ = dlist[j]
                            if ds_ in v and dlist[j - 1] in v and v[dlist[j - 1]][1] > 0:
                                if 9.8 <= (v[ds_][1] / v[dlist[j - 1]][1] - 1) * 100 <= 10.6:
                                    run += 1
                                    j -= 1
                                    continue
                            break
                        pool[c] = run
                if pool:
                    qq = get_quotes(list(pool.keys()))
                    for c, bd in pool.items():
                        v = qq.get(c)
                        if not v or v['prev'] <= 0 or v['open'] <= 0:
                            continue
                        gap = (v['open'] / v['prev'] - 1) * 100
                        limit = round(v['prev'] * 1.10, 2)
                        oneword = v['open'] >= limit - 0.011      # 一字板买不到
                        if oneword or gap <= 0 or gap > 7:
                            continue                              # 不接低开、不追一字
                        fresh.append(dict(code=c, name=v['name'], bd=bd, open=v['open'],
                                          gap=round(gap, 2),
                                          score=bd * 10 + min(gap, 7)))
                    fresh.sort(key=lambda x: -x['score'])
                    fresh = fresh[:5]
                    print('竞价新挑 %d 只（昨日涨停池 %d 只，剔除低开/一字/高开>7%%）' % (
                        len(fresh), len(pool)), flush=True)
    except Exception as e:
        print('竞价新挑失败（不影响主清单确认）：%s' % e, flush=True)

    codes = [s['code'] for s in sigs]
    q = get_quotes(codes)
    print('抓到 %d/%d 只开盘价' % (len(q), len(codes)), flush=True)

    rows = []
    for s in sigs:
        v = q.get(s['code'])
        if not v or v['prev'] <= 0 or v['open'] <= 0:
            rows.append(dict(s, open=None, gap=None, act='行情缺失·不买'))
            continue
        gap = (v['open'] / v['prev'] - 1) * 100
        # 不追高：高开超过 5% 放弃；低开也不追（不做低开接盘）
        if gap > 5:
            act = '高开过多·放弃'
        elif gap < -5:
            act = '低开过深·放弃'
        else:
            act = '可按开盘价买'
        rows.append(dict(s, open=round(v['open'], 2), gap=round(gap, 2), act=act))

    buy = [r for r in rows if r['act'] == '可按开盘价买']
    body = ['<div style="font-family:Microsoft YaHei,sans-serif;max-width:760px;margin:auto;color:#111">']
    body.append('<h2 style="font-size:18px;color:#c00">竞价执行确认 %s · 9:30 前下单</h2>' % now.strftime('%m-%d'))
    body.append('<p style="font-size:12px;color:#6b7280">策略版本：%s ｜ 生成时间：%s（北京时间）<br>'
                '本封<b>不新增标的</b>，只确认昨晚清单的实际开盘价。</p>' % (VERSION, now.strftime('%H:%M:%S')))
    body.append('<p style="font-size:13px">可买 <b>%d</b> 只。买入口径：按当前开盘价挂单；'
                '<b>卖出：跌 5%% 立即止损，最长持 10 个交易日</b>。高开 &gt;5%% 或低开 &lt;-5%% 的放弃。</p>' % len(buy))
    body.append('<table style="width:100%;border-collapse:collapse;font-size:13px">')
    body.append('<tr style="background:#f9fafb"><th align=left>代码</th><th align=left>名称</th>'
                '<th align=right>开盘价</th><th align=right>竞价涨幅</th><th align=left>动作</th>'
                '<th align=right>该状态日等权</th></tr>')
    for r in sorted(rows, key=lambda x: (x['act'] != '可按开盘价买', -(x.get('gap') or 0))):
        color = '#c00' if r['act'] == '可按开盘价买' else '#888'
        body.append('<tr><td><b>%s</b></td><td>%s</td><td align=right>%s</td>'
                    '<td align=right>%s</td><td style="color:%s"><b>%s</b></td>'
                    '<td align=right>%+.2f%%</td></tr>' % (
                        r['code'], r['name'], r['open'] if r['open'] else '—',
                        ('%+.2f%%' % r['gap']) if r['gap'] is not None else '—',
                        color, r['act'], r.get('state_deq', r.get('ann', 0))))
    body.append('</table>')
    if fresh:
        body.append('<h3 style="font-size:15px;margin-top:18px">竞价新挑（昨日涨停池 · 按身位）</h3>')
        body.append('<p style="font-size:12px;color:#6b7280">只在昨日涨停股里选；'
                    '<b>剔除低开、一字、高开&gt;7%</b>。按连板高度优先，最多 5 只。</p>')
        body.append('<table style="width:100%;border-collapse:collapse;font-size:13px">')
        body.append('<tr style="background:#f9fafb"><th align=left>代码</th><th align=left>名称</th>'
                    '<th align=right>昨日连板</th><th align=right>竞价开盘</th><th align=right>竞价涨幅</th>'
                    '<th align=left>身位</th></tr>')
        for r in fresh:
            pos_ = '龙头' if r['bd'] >= 3 else ('前排' if r['bd'] == 2 else '首板')
            body.append('<tr><td><b>%s</b></td><td>%s</td><td align=right>%d板</td>'
                        '<td align=right>%.2f</td><td align=right style="color:#c00"><b>%+.2f%%</b></td>'
                        '<td>%s</td></tr>' % (r['code'], r['name'], r['bd'], r['open'], r['gap'], pos_))
        body.append('</table>')
        body.append('<p style="font-size:12px;color:#6b7280">卖出：断板次日走；跌 5% 止损。</p>')
    body.append('</div>')
    html = ''.join(body)
    subj = '【竞价确认 v3】%s 清单%d只可买 + 新挑%d只 · 9:30 前下单' % (
        now.strftime('%m-%d'), len(buy), len(fresh))

    open(os.path.join(LOG, 'confirm_%s_v3.html' % now.strftime('%Y%m%d')), 'w', encoding='utf-8').write(html)
    if dry:
        print('[DRY]', subj, flush=True)
        for r in rows:
            print('  %s %s 开%s 竞价%s → %s' % (r['code'], r['name'], r['open'], r['gap'], r['act']), flush=True)
    else:
        send(subj, html)
        print('已发：%s' % subj, flush=True)
    with open(os.path.join(LOG, 'send.log'), 'a', encoding='utf-8') as f:
        f.write('%s | %s | %d只 | %s\n' % (now.strftime('%Y-%m-%d %H:%M:%S'), subj,
                                           len(buy), 'DRY' if dry else 'OK'))


if __name__ == '__main__':
    main()
