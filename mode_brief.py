# -*- coding: utf-8 -*-
"""mode_brief.py —— 竞价时段只发模式简报（不推个股）"""
import os, sys, json
from datetime import datetime, timezone, timedelta
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
BJ = timezone(timedelta(hours=8))


def main():
    import mode_predict, notify_v4
    md = mode_predict.today_mode()
    if not md:
        print('模式判定失败，不发', flush=True)
        return
    r = md['raw']
    d = dict(day=r['day'], stage=md['desc'], env=r, picks=[])
    html = notify_v4.build_brief(d, [])
    subj = '【模式简报】%s %s' % (r['day'], md['desc'])
    if '--dry' in sys.argv:
        print('[DRY]', subj, flush=True)
        return
    notify_v4.send(subj, html)
    print('已发：' + subj, flush=True)
    with open(os.path.join(BASE, '_push_logs', 'send.log'), 'a', encoding='utf-8') as f:
        f.write('%s | %s | 简报 | OK\n' % (datetime.now(BJ).strftime('%Y-%m-%d %H:%M:%S'), subj))


if __name__ == '__main__':
    main()
