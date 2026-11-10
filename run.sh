#!/bin/bash
# A股战法扫描 - 定时运行脚本
cd /opt/stock || exit 1
/usr/bin/python3 scanner.py >> /opt/stock/run.log 2>&1
