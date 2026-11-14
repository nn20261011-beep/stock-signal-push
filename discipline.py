# -*- coding: utf-8 -*-
"""
discipline.py —— 交易纪律状态机（不是网页那个 discipline.js）

维护一个状态文件，记录：连亏笔数、昨日组合盈亏、黑名单、当前模式。
每次开盘前调用 check_before_open()，返回 (允许开仓, 拦截原因列表, 仓位系数)。
"""
import os, json
from datetime import datetime, timezone, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(BASE, '_trading_state.json')
BJ = timezone(timedelta(hours=8))

DEFAULT = dict(
    loss_streak=0,
    last_daily_pnl=0.0,
    last_update='',
    blacklist=[],
    mode='four_type',
    equity=1.0,
    peak_equity=1.0,
    trades=[],
)


def load():
    if os.path.exists(STATE):
        try:
            d = json.load(open(STATE, encoding='utf-8'))
            for k, v in DEFAULT.items():
                d.setdefault(k, v)
            return d
        except Exception:
            pass
    return dict(DEFAULT)


def save(d):
    tmp = STATE + '.tmp'
    json.dump(d, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    os.replace(tmp, STATE)


def record_trade(pnl_pct, code='', note=''):
    """记录一笔已平仓交易：更新连亏、权益、交易流水"""
    d = load()
    d['loss_streak'] = (d['loss_streak'] + 1) if pnl_pct < 0 else 0
    d['equity'] = round(d['equity'] * (1 + pnl_pct / 100), 6)
    d['peak_equity'] = max(d['peak_equity'], d['equity'])
    d['trades'].append(dict(day=datetime.now(BJ).strftime('%Y-%m-%d'),
                            code=code, pnl=round(pnl_pct, 2), note=note))
    d['trades'] = d['trades'][-200:]
    d['last_update'] = datetime.now(BJ).strftime('%Y-%m-%d %H:%M')
    save(d)
    return d


def set_daily_pnl(pct):
    d = load()
    d['last_daily_pnl'] = round(float(pct), 2)
    d['last_update'] = datetime.now(BJ).strftime('%Y-%m-%d %H:%M')
    save(d)
    return d


def add_blacklist(code, reason=''):
    d = load()
    if code not in d['blacklist']:
        d['blacklist'].append(code)
    d['last_update'] = datetime.now(BJ).strftime('%Y-%m-%d %H:%M')
    save(d)
    return d


def check_before_open():
    """返回 (allow: bool, blocks: list[str], factor: float)"""
    d = load()
    blocks = []
    factor = 1.0
    if d['loss_streak'] >= 3:
        blocks.append('纪律：已连亏 %d 笔，今日空仓' % d['loss_streak'])
        return False, blocks, 0.0
    if d['last_daily_pnl'] <= -5.0:
        blocks.append('纪律：昨日组合 %.2f%%，今日仓位减半' % d['last_daily_pnl'])
        factor = 0.5
    if d['mode'] != 'four_type':
        blocks.append('纪律：当前只允许 four_type 模式，状态为 %s' % d['mode'])
        return False, blocks, 0.0
    # 回撤熔断：从峰值回撤 >=20% 停手
    dd = (d['equity'] / d['peak_equity'] - 1) * 100 if d['peak_equity'] > 0 else 0
    if dd <= -20:
        blocks.append('纪律：权益从峰值回撤 %.1f%%，触发熔断' % dd)
        return False, blocks, 0.0
    return True, blocks, factor


def selftest():
    import shutil
    bak = STATE + '.bak'
    if os.path.exists(STATE):
        shutil.copy(STATE, bak)
    try:
        save(dict(DEFAULT))
        ok = 0
        # 1 正常
        a, b, f = check_before_open()
        hit = a and not b and f == 1.0
        ok += hit
        print('  正常状态 → 允许=%s 拦截=%s 系数=%.1f %s' % (a, b, f, '✅' if hit else '❌'))
        # 2 连亏3
        for _ in range(3):
            record_trade(-3.0, '000001')
        a, b, f = check_before_open()
        hit = (not a) and f == 0.0 and any('连亏' in x for x in b)
        ok += hit
        print('  连亏3笔 → 允许=%s 拦截=%s %s' % (a, b, '✅' if hit else '❌'))
        # 3 单日亏损
        save(dict(DEFAULT)); set_daily_pnl(-6.0)
        a, b, f = check_before_open()
        hit = a and f == 0.5
        ok += hit
        print('  单日-6%% → 允许=%s 系数=%.1f %s' % (a, f, '✅' if hit else '❌'))
        # 4 模式错
        d = load(); d['mode'] = 'old'; save(d)
        a, b, f = check_before_open()
        hit = (not a)
        ok += hit
        print('  模式错 → 允许=%s %s' % (a, '✅' if hit else '❌'))
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
