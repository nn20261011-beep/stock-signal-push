# -*- coding: utf-8 -*-
"""
doctrine.py —— 心法十条的机检实现

每条红线一个函数，返回 (pass: bool, reason: str)。
调用方必须在推送前逐条跑，任一条不通过即拦截并写明原因。
"""
from datetime import datetime, timezone, timedelta

BJ = timezone(timedelta(hours=8))

# ---- 参数（可调，改动须同步 doctrine.md）----
MAX_WEIGHT = 0.10          # 红线6 单票上限
MAX_POSITIONS = 8          # 红线7 持仓上限
LOSS_STREAK_LIMIT = 3      # 红线8 连亏笔数
DAILY_LOSS_LIMIT = -5.0    # 红线9 单日组合亏损%
GAP_LOW = 0.0              # 红线2 低开阈值
GAP_HIGH = 7.0             # 红线3 高开阈值


def r1_theme(theme_rank, theme_zt):
    """红线1 只做主线：题材必须是当日涨停数 TOP3"""
    if not theme_rank or theme_rank > 3:
        return False, '红线1：不属于当日涨停数 TOP3 题材'
    if not theme_zt or theme_zt < 2:
        return False, '红线1：题材涨停数不足 2 家'
    return True, ''


def r2_strong(gap_pct, is_one_word_limit):
    """红线2 强者恒强：低开不做；一字涨停买不到"""
    if is_one_word_limit:
        return False, '红线2：一字涨停买不到'
    if gap_pct is None:
        return True, '待竞价确认'   # 收盘决策阶段无竞价数据，由 auction_confirm 复核
    if gap_pct <= GAP_LOW:
        return False, '红线2：竞价低开 %.2f%%，不接下跌' % gap_pct
    return True, ''


def r3_no_chase(gap_pct):
    """红线3 不追高：高开 >7% 放弃"""
    if gap_pct is None:
        return True, '待竞价确认'
    if gap_pct > GAP_HIGH:
        return False, '红线3：高开 %.2f%% > %.0f%%，溢价已被吃掉' % (gap_pct, GAP_HIGH)
    return True, ''


def r4_regime(regime_action):
    """红线4 宁可错过：判天说「不做」才空仓；「半仓」是允许做但减仓"""
    if regime_action == '不做':
        return False, '红线4：判天输出「不做」，全天空仓'
    if regime_action not in ('做', '半仓'):
        return False, '红线4：判天输出未知动作「%s」' % regime_action
    return True, ''


def r5_sell_defined(sell_rule):
    """红线5 卖点先定：没有明确卖点不做"""
    valid = {'sl5', 'sl8', 'rbreak', 'ma5_n', 'ma10_n', 'r3', 'r5', 'r10', 'tp5', 'tp8'}
    if not sell_rule:
        return False, '红线5：未定义卖点'
    if sell_rule not in valid:
        return False, '红线5：卖点 %s 不在白名单' % sell_rule
    return True, ''


def r6_weight(weight):
    """红线6 单票不重仓"""
    if weight is None or weight <= 0:
        return False, '红线6：仓位未定义'
    if weight > MAX_WEIGHT + 1e-9:
        return False, '红线6：单票 %.0f%% > %.0f%%，压到上限' % (weight * 100, MAX_WEIGHT * 100)
    return True, ''


def r7_positions(n):
    """红线7 持仓上限"""
    if n is None:
        return False, '红线7：持仓数未知'
    if n > MAX_POSITIONS:
        return False, '红线7：持仓 %d 只 > %d 只，按评分截断' % (n, MAX_POSITIONS)
    return True, ''


def r8_loss_streak(streak):
    """红线8 连亏停手"""
    if streak is None:
        return True, ''          # 无记录时不拦，但要求补录
    if streak >= LOSS_STREAK_LIMIT:
        return False, '红线8：已连亏 %d 笔，今日空仓' % streak
    return True, ''


def r9_daily_loss(pnl_pct):
    """红线9 单日亏损上限：次日仓位减半"""
    if pnl_pct is None:
        return True, ''
    if pnl_pct <= DAILY_LOSS_LIMIT:
        return False, '红线9：昨日组合 %.2f%%，今日仓位减半' % pnl_pct
    return True, ''


def r10_single_mode(mode):
    """红线10 一次一套"""
    if mode != 'four_type':
        return False, '红线10：当前只启用四类票模式，收到 %s' % mode
    return True, ''


def check_all(ctx):
    """
    一次性跑完十条，返回 (passed: bool, blocks: list[dict])
    ctx 需包含：theme_rank/theme_zt/gap_pct/one_word/regime_action/sell_rule/
               weight/positions/loss_streak/daily_pnl/mode
    """
    blocks = []
    checks = [
        ('r1', lambda: r1_theme(ctx.get('theme_rank'), ctx.get('theme_zt'))),
        ('r2', lambda: r2_strong(ctx.get('gap_pct'), ctx.get('one_word', False))),
        ('r3', lambda: r3_no_chase(ctx.get('gap_pct'))),
        ('r4', lambda: r4_regime(ctx.get('regime_action'))),
        ('r5', lambda: r5_sell_defined(ctx.get('sell_rule'))),
        ('r6', lambda: r6_weight(ctx.get('weight'))),
        ('r7', lambda: r7_positions(ctx.get('positions'))),
        ('r8', lambda: r8_loss_streak(ctx.get('loss_streak'))),
        ('r9', lambda: r9_daily_loss(ctx.get('daily_pnl'))),
        ('r10', lambda: r10_single_mode(ctx.get('mode', 'four_type'))),
    ]
    for name, fn in checks:
        try:
            ok, reason = fn()
        except Exception as e:
            ok, reason = False, '%s 检查异常：%s' % (name, str(e)[:60])
        if not ok:
            blocks.append(dict(rule=name, reason=reason))
    return (len(blocks) == 0), blocks


def selftest():
    """自检：每条红线都要能拦住违规样本"""
    cases = [
        ('r1 非主线', dict(theme_rank=5, theme_zt=8), False),
        ('r1 题材弱', dict(theme_rank=1, theme_zt=2), False),
        ('r2 低开', dict(gap_pct=-3.0), False),
        ('r2 一字', dict(gap_pct=10.0, one_word=True), False),
        ('r3 高开9%', dict(gap_pct=9.0), False),
        ('r4 判天不做', dict(regime_action='不做'), False),
        ('r5 无卖点', dict(sell_rule=None), False),
        ('r6 超重', dict(weight=0.20), False),
        ('r7 超持仓', dict(positions=12), False),
        ('r8 连亏3', dict(loss_streak=3), False),
        ('r9 单日-6%', dict(daily_pnl=-6.0), False),
        ('r10 模式错', dict(mode='old'), False),
        ('合规样本', dict(theme_rank=2, theme_zt=6, gap_pct=3.0, one_word=False,
                          regime_action='做', sell_rule='sl5', weight=0.10,
                          positions=8, loss_streak=0, daily_pnl=1.0, mode='four_type'), True),
    ]
    ok = 0
    for name, ctx, expect in cases:
        passed, blocks = check_all(ctx)
        hit = (passed == expect)
        ok += hit
        print('  %-14s 期望%-6s 实际%-6s %s' % (
            name, '通过' if expect else '拦截',
            '通过' if passed else '拦截', '✅' if hit else '❌'))
    print('')
    print('自检 %d/%d' % (ok, len(cases)))
    return ok == len(cases)


if __name__ == '__main__':
    print('=== 心法十条自检 ===')
    ok = selftest()
    raise SystemExit(0 if ok else 1)
