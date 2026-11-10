#!/bin/bash
# A股盘中扫描 —— 每 3 分钟由 cron 调用，只在交易时段实际执行
cd /opt/stock || exit 1

# 读取 GitHub 凭证（不在公开仓库里）
set -a
[ -f /opt/stock/gh.env ] && . /opt/stock/gh.env
set +a

export INTRADAY=1

# 判断是否交易时段（北京时间 9:25 - 15:05）
H=$(date +%H); M=$(date +%M)
T=$((10#$H * 60 + 10#$M))
if [ "$T" -lt 565 ] || [ "$T" -gt 905 ]; then
  exit 0
fi

# 跳过午休 11:35 - 12:55
if [ "$T" -gt 695 ] && [ "$T" -lt 775 ]; then
  exit 0
fi

/usr/bin/python3 scanner.py >> /opt/stock/run.log 2>&1
