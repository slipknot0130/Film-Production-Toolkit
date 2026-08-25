#!/usr/bin/env bash
# =============================================================================
# Film Production Toolkit - One-Click Setup for macOS / Linux
# 影视创作制片综合工具 - 一键部署（macOS / Linux 版）
#
# 用法：
#   chmod +x setup_and_run.sh     # 首次需赋予执行权限（仅一次）
#   ./setup_and_run.sh
#
# 说明：本项目不再提供打包安装包，拉取源码后本地运行即可。
#       本脚本自动完成：检测 Python → 创建并激活 venv → 安装依赖 → 启动应用。
#       macOS 系统 pip 多为 externally-managed，故默认使用虚拟环境 (./venv)，
#       避免污染系统 Python，也保证 update.py / start.py 共用同一套依赖。
# =============================================================================

echo ""
echo "============================================================"
echo "  Film Production Toolkit - One-Click Setup"
echo "  影视创作制片综合工具 - 一键部署 (macOS / Linux)"
echo "============================================================"
echo ""

# ── Step 1: 检测 Python3 ──
echo "[1/5] 检测 Python 环境..."
if ! command -v python3 >/dev/null 2>&1; then
    echo ""
    echo "  [ERROR] 未检测到 python3！"
    echo "  请先安装 Python 3.10+："
    echo "    macOS:  brew install python@3.12"
    echo "    官网:   https://www.python.org/downloads/"
    echo ""
    exit 1
fi

PY_VER=$(python3 -c "import sys; print('.'.join(map(str, sys.version_info[:3])))")
echo "  [OK] Python $PY_VER"

if ! python3 -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >/dev/null 2>&1; then
    echo "  [ERROR] Python 版本过低，需要 3.10+，当前: $PY_VER"
    echo "  请升级: https://www.python.org/downloads/"
    exit 1
fi

# ── Step 2: 准备虚拟环境 (venv) ──
echo ""
echo "[2/5] 准备虚拟环境 (venv)..."
if [ ! -d "venv" ]; then
    echo "  创建虚拟环境 ./venv ..."
    if ! python3 -m venv venv; then
        echo "  [ERROR] 创建 venv 失败。macOS 请先安装: brew install python@3.12"
        exit 1
    fi
fi
VENV_PY="venv/bin/python"
"$VENV_PY" -m pip install --upgrade pip --quiet
echo "  [OK] 虚拟环境就绪 (./venv)"

# ── Step 3: 安装依赖 ──
echo ""
echo "[3/5] 安装 Python 依赖 (首次可能需要几分钟)..."
if "$VENV_PY" -c "import streamlit" >/dev/null 2>&1; then
    echo "  [OK] 核心依赖已安装，跳过"
else
    echo "  正在安装依赖..."
    if ! "$VENV_PY" -m pip install -r requirements.txt --quiet; then
        echo "  [WARN] 完整依赖安装失败，尝试核心依赖..."
        "$VENV_PY" -m pip install streamlit openai httpx pandas python-docx requests python-dotenv openpyxl --quiet
    fi
    echo "  [OK] 依赖安装完成"
fi

# ── Step 4: 可选依赖检测 ──
echo ""
echo "[4/5] 检测可选依赖..."
if "$VENV_PY" -c "import crewai" >/dev/null 2>&1; then
    echo "  [OK] CrewAI 已安装（分镜工作台可用）"
else
    echo "  [INFO] CrewAI 未安装 — 分镜工作台功能不可用"
    echo "         如需使用，请运行: ./venv/bin/python -m pip install crewai langchain-openai"
fi

# ── Step 5: 启动应用 ──
echo ""
echo "[5/5] 启动应用（网页版）..."
echo ""
"$VENV_PY" start.py
