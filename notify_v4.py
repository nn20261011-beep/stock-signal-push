# -*- coding: utf-8 -*-
"""notify_v4.py —— 模式简报邮件（体系建成前不列个股）"""
import os, sys, json, smtplib, ssl, gzip, pickle
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.header import Header

BASE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(BASE, '_push_logs')
BJ = timezone(timedelta(hours=8))
SMTP_USER = os.environ.get('SMTP_USER', 'h1533165068@qq.com')
SMTP_PASS = os.environ.get('SMTP_PASS', 'xfboalpjikugjfgg')
MAIL_TO = os.environ.get('MAIL_TO', 'h1533165068@qq.com')

SELL_TXT = {'r1': 'T+2收盘卖（T+1开盘买）',
            'sl5': '跌5%止损/上限10日', 'sl8': '跌8%止损/上限10日',
            'rbreak': '断板次日走', 'r10': '持满10日', 'r5': '持满5日',
            'r3': '持满3日', 'tp8': '涨8%止盈', 'tp5': '涨5%止盈',
            'ma5_n': '跌破MA5走', 'ma10_n': '跌破MA10走'}

# 聚类模式 → 已验证战法。空字典 = 所有模式“暂无战法，不做”
# 只有通过「三段胜率门槛 + 扣0.2% + 跨模式对照」的战法才能填进来
MODE_STRATEGY = {}


def send(subject, html):
    msg = MIMEText(html, 'html', 'utf-8')
    msg['From'], msg['To'] = SMTP_USER, MAIL_TO
    msg['Subject'] = Header(subject, 'utf-8')
    s = smtplib.SMTP_SSL('smtp.qq.com', 465, timeout=25,
                         context=ssl.create_default_context())
    s.login(SMTP_USER, SMTP_PASS)
    s.sendmail(SMTP_USER, [MAIL_TO], msg.as_string())
    s.quit()


def already_sent_today(today):
    log = os.path.join(LOG, 'send.log')
    if not os.path.exists(log):
        return False
    for ln in open(log, encoding='utf-8').read().strip().split('\n'):
        if today in ln and ('决策 v4' in ln or '模式简报' in ln) and 'DRY' not in ln:
            return True
    return False


def build_brief(d, picks):
    """模式简报：只报模式、战法、信号数。不列个股。"""
    md = None
    try:
        import mode_predict
        md = mode_predict.today_mode()
    except Exception as e:
        print('模式判定失败：%s' % e, flush=True)
    env = d.get('env') or {}
    body = ['<div style="font-family:Microsoft YaHei,sans-serif;max-width:720px;color:#111">']
    body.append('<h2 style="font-size:18px">%s 模式简报</h2>' % d.get('day', ''))
    if md:
        r = md['raw']
        body.append('<p style="font-size:15px;background:#eef2ff;padding:10px;border-radius:6px">'
                    '<b>模式：%s %s</b><br>'
                    '<span style="font-size:12px;color:#374151">依据：涨停 %d 家、跌停 %d 家、赚钱 %+.2f%%、'
                    '最高 %d 板、梯队断层 %d、上涨占比 %.1f%%、中位 %+.2f%%、成交额分位 %.0f%%</span></p>'
                    % (md['mode'], md['desc'], r['zt_n'], r['dt_n'], r['earn'], r['max_bd'],
                       r['tier_gap'], r['up_ratio'], r['med_chg'], r['amt_pct']))
    else:
        body.append('<p style="font-size:15px;background:#eef2ff;padding:10px">'
                    '<b>模式：判定失败</b>（涨停 %s 家、赚钱 %s%%）</p>'
                    % (env.get('zt_n', '-'), env.get('earn', '-')))
    code = md['mode'] if md else None
    stg = MODE_STRATEGY.get(code) if code else None
    if stg:
        body.append('<p style="font-size:14px"><b>本模式战法</b>：%s %s（三段 %s%%，胜率 %.1f%%，历史均值）</p>'
                    % (stg['code'], stg['name'],
                       '/'.join('%+.2f' % v for v in stg['seg']), stg['win']))
    else:
        body.append('<p style="font-size:14px;color:#b45309"><b>本模式战法</b>：暂无验证通过的战法，不做。</p>')
    body.append('<p style="font-size:15px"><b>今日信号</b>：<b>%d</b> 只（个股清单暂停推送，体系建成后恢复）</p>'
                % (0 if not stg else len(picks)))
    body.append('<p style="font-size:11px;color:#6b7280;margin-top:10px">'
                '模式来自 K-means 聚类（K=3，轮廓系数 0.202，12 维市场特征），非手写阈值。'
                '战法须通过「三段胜率门槛 + 扣 0.2% 成本 + 跨模式对照」才列入本模式。</p></div>')
    return ''.join(body)


def main():
    dry = '--dry' in sys.argv
    now = datetime.now(BJ)
    today = now.strftime('%Y-%m-%d')
    if already_sent_today(today):
        print('今日已发过，跳过（%s）' % today, flush=True)
        return
    fp = os.path.join(LOG, 'decision_%s.json' % now.strftime('%Y%m%d'))
    if not os.path.exists(fp):
        cand = sorted([f for f in os.listdir(LOG) if f.startswith('decision_')])
        if not cand:
            print('无决策文件，跳过', flush=True)
            return
        fp = os.path.join(LOG, cand[-1])
    d = json.load(open(fp, encoding='utf-8'))
    picks = d.get('picks') or []
    html = build_brief(d, picks)
    subj = '【模式简报】%s %s' % (d.get('day', ''), d.get('stage', ''))
    if dry:
        print('[DRY]', subj, flush=True)
    else:
        send(subj, html)
        print('已发：%s' % subj, flush=True)
    with open(os.path.join(LOG, 'send.log'), 'a', encoding='utf-8') as f:
        f.write('%s | %s | 简报 | %s\n' % (now.strftime('%Y-%m-%d %H:%M:%S'), subj,
                                          'DRY' if dry else 'OK'))


if __name__ == '__main__':
    main()
