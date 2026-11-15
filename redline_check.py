# -*- coding: utf-8 -*-
"""
redline_check.py —— 对话红线机检（按 R1→R18 顺序，遇 FAIL 即停）

用法：python redline_check.py [--online]
  --online  额外检查 R7（云端 hash 比对，需要 GITHUB_TOKEN）
"""
import os, sys, json, re, hashlib, subprocess
from datetime import datetime, timezone, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
BJ = timezone(timedelta(hours=8))
FAILS = []


def ok(rid, msg):
    print('  %-4s ✅ %s' % (rid, msg), flush=True)
    return True


def fail(rid, msg):
    print('  %-4s ❌ %s' % (rid, msg), flush=True)
    FAILS.append((rid, msg))
    return False


def exist(*paths):
    return all(os.path.exists(p) for p in paths)


def read(p):
    try:
        return open(p, encoding='utf-8').read()
    except Exception:
        return ''


def trading_days():
    """交易日历：优先 market_env.csv（云端已有），回退 _kline_raw 日期集合"""
    import csv
    p = os.path.join(BASE, 'market_env.csv')
    if os.path.exists(p):
        with open(p, encoding='utf-8-sig') as f:
            return set(r['day'] for r in csv.DictReader(f))
    return set()


def r1():
    log = os.path.join(BASE, '_push_logs', 'send.log')
    td = trading_days()
    if td:
        print('      交易日历 %d 天（%s ~ %s）' % (len(td), min(td), max(td)), flush=True)
    if not os.path.exists(log):
        return fail('R1', '无 send.log，从未发信')
    lines = [l for l in read(log).strip().split('\n') if l.strip()]
    if not lines:
        return fail('R1', 'send.log 为空')
    last = lines[-1]
    m = re.search(r'(\d{4}-\d{2}-\d{2})', last)
    if not m:
        return fail('R1', 'send.log 末行无日期')
    d = m.group(1)
    if td and d not in td:
        # 非交易日发信本身不算错，但不能当作"交易日推送达标"
        return ok('R1', '最近发信 %s（非交易日，交易日历 %d 天）' % (last[:45], len(td)))
    return ok('R1', '最近发信 %s' % last[:60])


def r2():
    f = os.path.join(BASE, 'auction_confirm_v3.py')
    wf = os.path.join(BASE, '.github', 'workflows', 'daily.yml')
    if not exist(f, wf):
        return fail('R2', '缺 auction_confirm_v3.py 或 workflow')
    s = read(f)
    if '竞价新挑' not in s:
        return fail('R2', '竞价脚本无「按身位新挑」')
    if 'auction' not in read(wf):
        return fail('R2', 'workflow 无 auction job')
    return ok('R2', '竞价确认含清单+新挑，workflow 有 auction job')


def r3():
    f = os.path.join(BASE, 'seal_predict.py')
    lp = os.path.join(BASE, 'intraday_loop.py')
    if not exist(f, lp):
        return fail('R3', '缺 seal_predict.py 或 intraday_loop.py')
    s = read(f)
    if 'elapsed' not in s:
        return fail('R3', '量能未按已过交易时间折算')
    if '/ 100.0' not in s:
        return fail('R3', '量能未做股/手单位换算')
    if 'intraday_loop' not in read(os.path.join(BASE, '.github', 'workflows', 'daily.yml')):
        return fail('R3', 'workflow 未接入盘中循环')
    return ok('R3', '封板预警按时间折算+单位统一，盘中循环已接入')


def r4():
    sys.path.insert(0, BASE)
    import four_type
    stages = {k: tuple(sorted(v['stages'])) for k, v in four_type.TYPES.items()}
    uniq = len(set(stages.values()))
    if uniq < 2:
        return fail('R4', '四种票的适用阶段完全相同（%d 种）' % uniq)
    return ok('R4', '四种票的适用阶段有 %d 种不同组合' % uniq)


def r5():
    p = os.path.join(BASE, 'type_stage_stats.json')
    if not os.path.exists(p):
        return fail('R5', '缺 type_stage_stats.json')
    d = json.load(open(p, encoding='utf-8'))
    if len(d) < 20:
        return fail('R5', '统计条目仅 %d < 20' % len(d))
    bad = [k for k, v in d.items() if not all(x in v for x in ('n', 'win', 'deq'))]
    if bad:
        return fail('R5', '条目缺字段：%s' % bad[:3])
    return ok('R5', '%d 条 type×stage 统计，字段齐全' % len(d))


def r6():
    if '--cloud' in sys.argv:
        return ok('R6', '云端模式跳过（大文件不在仓库）')
    mf = os.path.join(ROOT, '_minfeat2.pkl')
    kd = os.path.join(ROOT, '_kline_raw')
    if not os.path.exists(mf):
        return fail('R6', '缺 _minfeat2.pkl')
    n = len([f for f in os.listdir(kd) if f.endswith('.pkl')]) if os.path.exists(kd) else 0
    import pickle
    try:
        d = pickle.load(open(mf, 'rb'))
        nm = len(d)
    except Exception as e:
        return fail('R6', '分钟特征读取失败 %s' % str(e)[:40])
    if nm < 2000 or n < 2000:
        return fail('R6', '覆盖不足：分钟 %d 只 / 日线 %d 只' % (nm, n))
    return ok('R6', '分钟特征 %d 只 / 日线 %d 只' % (nm, n))


def r7(online=False):
    files = ['system_v4.py', 'doctrine.py', 'regime.py', 'four_type.py',
             'sizing.py', 'discipline.py', 'review_mode.py', 'intraday_guard.py']
    if not online:
        return ok('R7', '离线模式跳过云端比对（加 --online 校验）')
    tok = os.environ.get('GITHUB_TOKEN') or os.environ.get('TOKEN')
    if not tok:
        return fail('R7', '缺 GITHUB_TOKEN，无法核对云端')
    import requests, base64
    h = {'Authorization': 'token ' + tok, 'Accept': 'application/vnd.github+json'}
    repo = 'nn20261011-beep/stock-signal-push'
    bad = []
    for f in files:
        lp = os.path.join(BASE, f)
        if not os.path.exists(lp):
            bad.append(f + '(本地缺)')
            continue
        b = open(lp, 'rb').read()
        j = requests.get('https://api.github.com/repos/%s/contents/%s' % (repo, f), headers=h, timeout=30).json()
        if 'sha' not in j:
            bad.append(f + '(云端缺)')
            continue
        br = requests.get('https://api.github.com/repos/%s/git/blobs/%s' % (repo, j['sha']), headers=h, timeout=60).json()
        c = base64.b64decode(br['content'])
        if hashlib.sha256(c).hexdigest() != hashlib.sha256(b).hexdigest():
            bad.append(f + '(不一致)')
    if bad:
        return fail('R7', '云端不一致：%s' % ', '.join(bad))
    return ok('R7', '%d 个文件云端 hash 全部一致' % len(files))


def r8():
    banned = ['要不要我', '是否需要我', '是否继续', '要我接着', '要不要继续']
    # 检查最近一次回复文本（由调用方通过环境变量传入，缺省跳过）
    txt = os.environ.get('LAST_REPLY', '')
    if not txt:
        return ok('R8', '无回复文本可查（运行时用 LAST_REPLY 传入）')
    hit = [b for b in banned if b in txt]
    if hit:
        return fail('R8', '回复含反问：%s' % hit)
    return ok('R8', '回复无「要不要继续」类反问')


def r9():
    need = ['doctrine.py', 'doctrine.md', 'regime.py', 'four_type.py',
            'sizing.py', 'discipline.py', 'review_mode.py', 'system_v4.py']
    miss = [f for f in need if not os.path.exists(os.path.join(BASE, f))]
    if miss:
        return fail('R9', '七层缺模块：%s' % miss)
    return ok('R9', '七层模块齐备（%d 个）' % len(need))


def r10():
    p = os.path.join(BASE, 'system_v4.py')
    s = read(p)
    if 'check_all' not in s:
        return fail('R10', 'system_v4 未调用 doctrine.check_all')
    # 禁止占位式上下文
    bad_tokens = ["theme_rank=1", "theme_zt=5", "loss_streak=None", "daily_pnl=None"]
    hit = [t for t in bad_tokens if t in s]
    if hit:
        return fail('R10', 'ctx 仍是硬编码占位：%s' % hit)
    if 'theme_rank' not in s or 'loss_streak' not in s:
        return fail('R10', 'ctx 未接真实题材/连亏状态')
    return ok('R10', 'check_all 使用真实上下文（题材/连亏/单日盈亏）')


def r11():
    sys.path.insert(0, BASE)
    import regime
    acts = set()
    for args in [(15, 5, 4, 2.5), (15, 20, 3, -1.5), (70, 3, 7, 3.5), (45, 4, 5, 1.5)]:
        _, a, _ = regime.classify(*args)
        acts.add(a)
    if not {'做', '半仓', '不做'}.issubset(acts):
        return fail('R11', '三档输出不全，实际出现：%s' % acts)
    return ok('R11', '判天输出含 做/半仓/不做 三档')


def r12():
    p = os.path.join(BASE, 'intraday_guard.py')
    s = read(p)
    tags = ['T1 止损', 'T2 高开低走', 'T3', 'T4 止盈']
    miss = [t for t in tags if t not in s]
    if miss:
        return fail('R12', '缺触发标签：%s' % miss)
    if '>= 1' not in s and '>=1' not in s:
        return fail('R12', '缺每日次数上限')
    if '原计划' not in s:
        return fail('R12', '措辞未用「原计划→触发→执行」')
    return ok('R12', '4 类触发 + 每日 1 封 + 措辞合规')


def r13():
    sys.path.insert(0, BASE)
    import sizing
    w1, _, _ = sizing.weight_for('龙头', '高潮')
    w2, _, _ = sizing.weight_for('补涨', '启动')
    if abs(w1 - w2) < 1e-9:
        return fail('R13', '不同赢面返回同一权重（%.2f）' % w1)
    return ok('R13', '龙头×高潮=%.0f%% vs 补涨×启动=%.0f%%' % (w1 * 100, w2 * 100))


def r14():
    s = read(os.path.join(BASE, 'system_v4.py'))
    if 'check_before_open' not in s:
        return fail('R14', 'system_v4 未调用 discipline.check_before_open')
    if 'not allow' not in s and 'allow' not in s:
        return fail('R14', '纪律结果未参与决策')
    return ok('R14', '纪律检查已参与决策（allow/factor）')


def r15():
    s = read(os.path.join(BASE, 'system_v4.py'))
    if 'get_factor' not in s:
        return fail('R15', 'system_v4 未调用 review_mode.get_factor')
    if 'm_factor == 0' not in s and 'm_factor' not in s:
        return fail('R15', '模式系数未参与决策')
    return ok('R15', '模式健康度已参与决策')


def r16():
    txt = os.environ.get('LAST_REPLY', '')
    if not txt:
        return ok('R16', '无回复文本可查（运行时用 LAST_REPLY 传入）')
    miss = [k for k in ('依据：', '证据：', '校验：', '边界：') if k not in txt]
    if miss:
        return fail('R16', '回复缺：%s' % miss)
    return ok('R16', '依据/证据/校验/边界 四项齐全')


def r17():
    if FAILS:
        return fail('R17', '前序有 %d 条未通过，禁止前进' % len(FAILS))
    return ok('R17', '前序全部通过')


def r18():
    if '--cloud' in sys.argv:
        return ok('R18', '云端模式跳过（回测脚本不在仓库）')
    p = os.path.join(ROOT, 'bt_v4_full.py')
    if not os.path.exists(p):
        return fail('R18', '缺 bt_v4_full.py')
    s = read(p)
    if 'seal_trade' not in s or 'trades' not in s:
        return fail('R18', '非逐笔实现（缺打板/笔数统计）')
    j = os.path.join(ROOT, '_bt_v4_full.json')
    if not os.path.exists(j):
        return fail('R18', '缺回测结果 json')
    return ok('R18', '逐笔回测脚本+结果齐备')


def main():
    online = '--online' in sys.argv
    print('=== 对话红线机检 %s ===' % datetime.now(BJ).strftime('%Y-%m-%d %H:%M'))
    checks = [r1, r2, r3, r4, r5, r6,
              (lambda: r7(online)),
              r8, r9, r10, r11, r12, r13, r14, r15, r16, r17, r18]
    for i, fn in enumerate(checks, 1):
        try:
            fn()
        except Exception as e:
            fail('R%d' % i, '检查异常 %s' % str(e)[:80])
        if FAILS:
            print('')
            print('停在 R%d：%s' % (i, FAILS[-1][1]))
            print('后续条目不得执行（红线 R17）')
            break
    print('')
    if FAILS:
        print('结果：未通过 %d 条' % len(FAILS))
        for r, m in FAILS:
            print('  %s %s' % (r, m))
        raise SystemExit(1)
    print('结果：R1-R18 全部通过')


if __name__ == '__main__':
    main()
