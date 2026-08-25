#!/usr/bin/env bash
# =============================================================================
# Film Production Toolkit - One-Click Launch for macOS / Linux
# 影视创作制片综合工具 - 一键启动（macOS / Linux 版）
#
# 用法：
#   chmod +x start.sh            # 首次需赋予执行权限（仅一次）
#   ./start.sh
#
# 说明：优先使用项目内的 ./venv 虚拟环境（由 setup_and_run.sh 创建），
#       若不存在则回退到系统 python3。启动后自动打开浏览器网页版。
# =============================================================================

# 优先使用项目 venv，否则回退系统 python3
if [ -x "venv/bin/python" ]; then
    PY="venv/bin/python"
else
    PY="python3"
fi

exec "$PY" start.py
