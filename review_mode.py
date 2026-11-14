# -*- coding: utf-8 -*-
"""
review_mode.py —— 模式有效性统计与自动降档

每笔平仓后由 discipline.record_trade 记录；本模块读最近 N 笔，判断模式是否还在有效期。
规则（数据驱动阈值，可调）：
  最近 20 笔平均 <= -3%  → 停手（factor 0）
  最近 20 笔平均 <  0    → 降档（factor 0.5）
  最近 20 笔平均 >= 0    → 正常（factor 1.0）
  样本 < 10 笔           → 不判断（factor 1.0），避免小样本误杀
"""
import os, json
from datetime import datetime, timezone, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(BASE, '_trading_state.json')
HEALTH = os.path.join(BASE, '_mode_health.json')
BJ = timezone(timedelta(hours=8))

MIN_SAMPLES = 10
WINDOW = 20
STOP_BELOW = -3.0
HALVE_BELOW = 0.0


def load_state():
    if os.path.exists(STATE):
        try:
            return json.load(open(STATE, encoding='utf-8'))
        except Exception:
            pass
    return dict(trades=[])


def evaluate():
    st = load_state()
    trades = st.get('trades') or []
    recent = trades[-WINDOW:]
    n = len(recent)
    if n < MIN_SAMPLES:
        out = dict(factor=1.0, n=n, avg=None,
                   verdict='样本不足（%d<%d），不降档' % (n, MIN_SAMPLES))
    else:
        avg = sum(t['pnl'] for t in recent) / n
        if avg <= STOP_BELOW:
            out = dict(factor=0.0, n=n, avg=round(avg, 2),
                       verdict='近%d笔均值 %.2f%%，模式失效，停手' % (n, avg))
        elif avg < HALVE_BELOW:
            out = dict(factor=0.5, n=n, avg=round(avg, 2),
                       verdict='近%d笔均值 %.2f%%，模式转弱，仓位减半' % (n, avg))
        else:
            out = dict(factor=1.0, n=n, avg=round(avg, 2),
                       verdict='近%d笔均值 %.2f%%，模式正常' % (n, avg))
    out['updated'] = datetime.now(BJ).strftime('%Y-%m-%d %H:%M')
    json.dump(out, open(HEALTH, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return out


def get_factor():
    if os.path.exists(HEALTH):
        try:
            d = json.load(open(HEALTH, encoding='utf-8'))
            # 超过 3 天未更新则重算
            upd = d.get('updated', '')
            if upd[:10] == datetime.now(BJ).strftime('%Y-%m-%d'):
                return float(d.get('factor', 1.0)), d.get('verdict', '')
        except Exception:
            pass
    d = evaluate()
    return float(d['factor']), d['verdict']


def selftest():
    import shutil
    bak = STATE + '.bak'
    if os.path.exists(STATE):
        shutil.copy(STATE, bak)
    try:
        ok = 0
        # 1 样本不足
        json.dump(dict(trades=[dict(pnl=-5.0)]), open(STATE, 'w'))
        d = evaluate()
        hit = d['factor'] == 1.0 and '样本不足' in d['verdict']
        ok += hit
        print('  样本1笔 → factor=%.1f %s' % (d['factor'], '✅' if hit else '❌'))
        # 2 正常
        json.dump(dict(trades=[dict(pnl=1.0)] * 15), open(STATE, 'w'))
        d = evaluate()
        hit = d['factor'] == 1.0
        ok += hit
        print('  15笔+1.0%% → factor=%.1f %s' % (d['factor'], '✅' if hit else '❌'))
        # 3 降档
        json.dump(dict(trades=[dict(pnl=-1.0)] * 15), open(STATE, 'w'))
        d = evaluate()
        hit = d['factor'] == 0.5
        ok += hit
        print('  15笔-1.0%% → factor=%.1f %s' % (d['factor'], '✅' if hit else '❌'))
        # 4 停手
        json.dump(dict(trades=[dict(pnl=-5.0)] * 15), open(STATE, 'w'))
        d = evaluate()
        hit = d['factor'] == 0.0
        ok += hit
        print('  15笔-5.0%% → factor=%.1f %s' % (d['factor'], '✅' if hit else '❌'))
        print('')
        print('自检 %d/4' % ok)
        return ok == 4
    finally:
        if os.path.exists(bak):
            shutil.move(bak, STATE)
        else:
            try:
                os.remove(STATE)
            except Exception:
                pass


if __name__ == '__main__':
    raise SystemExit(0 if selftest() else 1)
