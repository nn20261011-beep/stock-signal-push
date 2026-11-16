# -*- coding: utf-8 -*-
"""
intraday_loop.py —— 一次云端运行内多次盘中检查，规避 GitHub schedule 限流

GitHub 会把 */5 的 cron 限流到约 1 小时一次（11-13 实测 6 次运行，间隔 50-60 分钟）。
故一次 job 内自旋：每 CHECK_GAP 秒跑一次 seal_predict.py + intraday_guard.py，共 ROUNDS 次。
默认 4 轮 × 180 秒 = 覆盖 12 分钟；配合多个错峰 cron 提高覆盖率。
"""
import os, sys, time, subprocess
from datetime import datetime, timezone, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
BJ = timezone(timedelta(hours=8))
PY = sys.executable


def in_session():
    now = datetime.now(BJ)
    hm = now.hour * 100 + now.minute
    return 930 <= hm <= 1450 and not (1130 < hm < 1300)


def main():
    force = '--force' in sys.argv
    dry = '--dry' in sys.argv
    rounds = int(os.environ.get('INTRADAY_ROUNDS', '4'))
    gap = int(os.environ.get('INTRADAY_GAP', '600'))
    if not force and not in_session():
        print('%s 不在盘中，跳过' % datetime.now(BJ).strftime('%H:%M'), flush=True)
        return
    args = []
    if dry:
        args.append('--dry')
    if force:
        args.append('--force')
    for i in range(rounds):
        print('=== 第 %d/%d 轮 %s ===' % (i + 1, rounds,
              datetime.now(BJ).strftime('%H:%M:%S')), flush=True)
        for script in ('seal_predict.py', 'intraday_guard.py'):
            try:
                r = subprocess.run([PY, os.path.join(BASE, script)] + args,
                                   cwd=BASE, timeout=180, capture_output=True, text=True)
                tail = (r.stdout or '').strip().split('\n')[-4:]
                for ln in tail:
                    print('  [%s] %s' % (script, ln[:140]), flush=True)
                if r.returncode != 0:
                    print('  [%s] 非零退出 %s' % (script, r.returncode), flush=True)
                    print('  stderr:', (r.stderr or '')[-300:], flush=True)
            except subprocess.TimeoutExpired:
                print('  [%s] 超时' % script, flush=True)
            except Exception as e:
                print('  [%s] 异常 %s' % (script, str(e)[:100]), flush=True)
        if i < rounds - 1:
            time.sleep(gap)
    print('盘中检查循环结束', flush=True)


if __name__ == '__main__':
    main()
