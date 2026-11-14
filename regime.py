# -*- coding: utf-8 -*-
"""
regime.py —— 判天：情绪五阶段 + 三档动作

阈值来源（不是拍脑袋，是 market_env.csv 2348 天分组回测，见 docstring 末表）：
  未来5日全市场等权收益，按 (涨停数 × 赚钱效应) 交叉分组：

        赚钱<-1  -1~1   1~3    >3
  涨停<20   +0.23  +0.36  -0.50  -0.91   ← 涨停少但赚钱高 = 退潮（最差）
  20-35    +0.26  +0.08  +0.13  -0.23
  35-55    +0.30  +0.76  -0.06  +0.64
  >55      (样本2) -0.22  +0.35  +0.76   ← 涨停多且赚钱高 = 主升

  基准：未来5日 +0.18%
"""
from datetime import datetime, timezone, timedelta

BJ = timezone(timedelta(hours=8))

# 三档 → 仓位参数（与 doctrine 红线 6/7 兼容）
ACTIONS = {
    # weight = 单票权重；max_picks = 最多持仓数；exposure = 总仓位上限（=weight×max_picks）
    '做':   dict(weight=0.10, max_picks=8, exposure=0.80, label='正常'),
    '半仓': dict(weight=0.05, max_picks=4, exposure=0.20, label='半仓'),
    '不做': dict(weight=0.0,  max_picks=0, exposure=0.00, label='空仓'),
}


def classify(zt_n, dt_n, max_bd, earn):
    """返回 (阶段, 动作, 理由)"""
    if zt_n is None or earn is None:
        return '未知', '不做', '环境数据缺失'
    zt_n = float(zt_n)
    earn = float(earn)
    max_bd = float(max_bd or 0)

    # 退潮：涨停少但赚钱效应高 —— 少数票拉、多数票跌，最差组合
    if zt_n < 20 and earn > 1:
        return '退潮', '不做', '涨停仅 %.0f 家但赚钱效应 %+.2f%%，少数票撑指数，历史未来5日 -0.50~-0.91%%' % (zt_n, earn)
    # 冰点：涨停少且赚钱效应低 —— 反转机会
    if zt_n < 20 and earn <= 1:
        return '冰点', '半仓', '涨停 %.0f 家、赚钱 %+.2f%%，历史未来5日 +0.23~+0.36%%，反转试仓' % (zt_n, earn)
    # 高潮：涨停多 + 赚钱高 + 高位
    if zt_n > 55 and earn > 1:
        if max_bd >= 6:
            return '高潮', '做', '涨停 %.0f 家、赚钱 %+.2f%%、最高 %.0f 板，主升浪（历史 +0.86%%）' % (zt_n, earn, max_bd)
        return '高潮', '做', '涨停 %.0f 家、赚钱 %+.2f%%，历史未来5日 +0.35~+0.76%%' % (zt_n, earn)
    # 高潮但赚钱效应中性 —— 打折
    if zt_n > 55 and -1 <= earn <= 1:
        return '高潮分化', '半仓', '涨停 %.0f 家但赚钱 %+.2f%%，历史 -0.22%%，降档' % (zt_n, earn)
    # 发酵
    if 35 <= zt_n <= 55 and earn > -1:
        return '发酵', '做', '涨停 %.0f 家、赚钱 %+.2f%%，历史 +0.13~+0.76%%' % (zt_n, earn)
    # 启动
    if 20 <= zt_n < 35:
        return '启动', '半仓', '涨停 %.0f 家、赚钱 %+.2f%%，历史 +0.08~+0.26%%，试仓' % (zt_n, earn)
    # 其余
    if zt_n >= 35 and earn <= -1:
        return '发酵转弱', '半仓', '涨停 %.0f 家但赚钱 %+.2f%%，降档' % (zt_n, earn)
    return '震荡', '半仓', '涨停 %.0f 家、赚钱 %+.2f%%，无显著优势' % (zt_n, earn)


def params(action):
    return ACTIONS.get(action, ACTIONS['不做'])


def selftest():
    cases = [
        ('退潮-涨停少赚钱高', (15, 5, 4, 2.5), '退潮', '不做'),
        ('冰点-涨停少赚钱低', (15, 20, 3, -1.5), '冰点', '半仓'),
        ('高潮-涨停多赚钱高', (70, 3, 7, 3.5), '高潮', '做'),
        ('高潮分化', (70, 5, 5, 0.2), '高潮分化', '半仓'),
        ('发酵', (45, 4, 5, 1.5), '发酵', '做'),
        ('启动', (25, 8, 4, 0.5), '启动', '半仓'),
        ('数据缺失', (None, None, None, None), '未知', '不做'),
    ]
    ok = 0
    for name, args, exp_stage, exp_act in cases:
        s, a, why = classify(*args)
        hit = (s == exp_stage and a == exp_act)
        ok += hit
        print('  %-18s → %-6s %-4s %s' % (name, s, a, '✅' if hit else '❌ 期望 %s/%s' % (exp_stage, exp_act)))
    print('')
    print('自检 %d/%d' % (ok, len(cases)))
    return ok == len(cases)


if __name__ == '__main__':
    print('=== 判天五阶段自检 ===')
    raise SystemExit(0 if selftest() else 1)
