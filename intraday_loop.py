# -*- coding: utf-8 -*-
"""
intraday_loop.py —— 一个 job 覆盖整个交易时段（9:30~14:50，320 分钟）

旧版问题：rounds=4 × gap=600s = 30 分钟，配合 timeout-minutes:30 只能覆盖 99 分钟
（11-25 实测 43%），而 GitHub cron 被限流到 51~86 分钟一次，开盘 38 分钟完全没看。

新版：
  - 一次 job 自旋到收盘，每轮判时段；不在盘中就等到 9:30，而不是直接退出
  - 每轮跑 seal_predict.py + intraday_guard.py，实测一轮约 12 秒
  - 320 分钟 < GitHub 单 job 上限 360 分钟（timeout-minutes: 360）
  - 同票去重由 seal_predict.py 里的 seal_sent_日期.json 负责
"""
import os, sys, time, subprocess
from datetime import datetime, timezone, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
BJ = timezone(timedelta(hours=8))
PY = sys.executable

# 交易时段（北京）
OPEN_HM = 930
CLOSE_HM = 1450
LUNCH_A = 1130
LUNCH_B = 1300


def now_bj():
    return datetime.now(BJ)


def hm_now():
    n = now_bj()
    return n.hour * 100 + n.minute


def in_session(hm=None):
    hm = hm if hm is not None else hm_now()
    return OPEN_HM <= hm <= CLOSE_HM and not (LUNCH_A < hm < LUNCH_B)


def wait_until_open():
    """9:30 前启动：等到开盘。每 30 秒醒一次，避免长 sleep 被 runner 回收。"""
    while hm_now() < OPEN_HM:
        print('等待开盘，当前 %s' % now_bj().strftime('%H:%M:%S'), flush=True)
        time.sleep(30)


def run_round(args, idx):
    """跑一轮 seal_predict + intraday_guard，返回耗时秒数"""
    t0 = time.time()
    print('=== 第 %d 轮 %s ===' % (idx, now_bj().strftime('%H:%M:%S')), flush=True)
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
    return time.time() - t0


def main():
    force = '--force' in sys.argv
    dry = '--dry' in sys.argv
    rounds_cap = int(os.environ.get('INTRADAY_ROUNDS', '0'))   # 0 = 跑到收盘
    gap = int(os.environ.get('INTRADAY_GAP', '0'))             # 默认 0，实测一轮已 12 秒

    args = []
    if dry:
        args.append('--dry')
    if force:
        args.append('--force')

    t_start = now_bj()
    print('启动 %s | 目标覆盖 9:30~14:50 (320 分钟) | rounds=%s gap=%ss' % (
        t_start.strftime('%H:%M:%S'), rounds_cap or '至收盘', gap), flush=True)

    if not force:
        wait_until_open()

    idx = 0
    scanned_min = 0
    last_hm = None
    while True:
        hm = hm_now()
        if not force and hm > CLOSE_HM:
            print('已过 14:50，结束', flush=True)
            break
        if not force and LUNCH_A < hm < LUNCH_B:
            if last_hm != hm:
                print('午休 %s，停扫' % now_bj().strftime('%H:%M:%S'), flush=True)
                last_hm = hm
            time.sleep(20)
            continue

        idx += 1
        cost = run_round(args, idx)
        scanned_min += cost / 60.0
        if rounds_cap and idx >= rounds_cap:
            print('达到 rounds 上限 %d，结束' % rounds_cap, flush=True)
            break
        if gap > 0:
            time.sleep(gap)

    t_end = now_bj()
    # 覆盖分钟：从首次扫描到末次扫描的墙钟时间（含午休扣除）
    wall = (t_end - t_start).total_seconds() / 60.0
    print('结束 %s | 运行 %d 轮 | 墙钟 %.1f 分钟 | 实际扫描耗时 %.1f 分钟' % (
        t_end.strftime('%H:%M:%S'), idx, wall, scanned_min), flush=True)


if __name__ == '__main__':
    main()
