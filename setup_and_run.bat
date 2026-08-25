@echo off
chcp 65001 >nul 2>&1
title Film Production Toolkit - Setup & Run

echo.
echo ============================================================
echo   Film Production Toolkit - One-Click Setup
echo   影视创作制片综合工具 - 一键部署
echo ============================================================
echo.

:: ── Step 1: 检测 Python ──
echo [1/5] 检测 Python 环境...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo   [ERROR] 未检测到 Python！
    echo   请安装 Python 3.10+ : https://www.python.org/downloads/
    echo   安装时请勾选 "Add Python to PATH"
    echo.
    pause
    exit /b 1
)

for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PY_VER=%%v
echo   [OK] Python %PY_VER%

:: 检测版本是否 >= 3.10
python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if %errorlevel% neq 0 (
    echo   [ERROR] Python 版本过低，需要 3.10+
    echo   当前版本: %PY_VER%
    echo   请升级: https://www.python.org/downloads/
    pause
    exit /b 1
)

:: ── Step 2: 检测 pip ──
echo.
echo [2/5] 检测 pip...
python -m pip --version >nul 2>&1
if %errorlevel% neq 0 (
    echo   [ERROR] pip 不可用，请重新安装 Python 并勾选 pip
    pause
    exit /b 1
)
echo   [OK] pip 可用

:: ── Step 3: 安装依赖 ──
echo.
echo [3/5] 检测并安装 Python 依赖...

:: 检查是否已安装核心依赖（避免每次重复安装）
python -c "import streamlit" >nul 2>&1
if %errorlevel% neq 0 (
    echo   正在安装依赖（首次可能需要几分钟）...
    python -m pip install -r "%~dp0requirements.txt" --quiet
    if %errorlevel% neq 0 (
        echo   [WARN] 部分依赖安装失败，尝试核心依赖...
        python -m pip install streamlit openai httpx pandas python-docx requests python-dotenv openpyxl --quiet
    )
    echo   [OK] 依赖安装完成
) else (
    echo   [OK] 核心依赖已安装
)

:: ── Step 4: 可选依赖 CrewAI（尽力安装，失败不阻断）──
echo.
echo [4/5] 可选依赖 CrewAI（分镜 4-Agent 矩阵，非必须）...
python -c "import crewai" >nul 2>&1
if %errorlevel% neq 0 (
    echo   [INFO] 正在尝试安装 CrewAI（失败不影响分镜轻量引擎）...
    python -m pip install -r "%~dp0requirements-crewai.txt" --quiet 2>nul
    if %errorlevel% equ 0 (
        echo   [OK] CrewAI 安装成功（分镜 4-Agent 矩阵可用）
    ) else (
        echo   [WARN] CrewAI 安装失败（常见于 Mac M1 个别原生依赖编译）。
        echo           分镜功能仍可用：程序会自动切换至轻量引擎（OpenAI 直调）。
        echo           如需 4-Agent 矩阵，可手动重试: pip install -r requirements-crewai.txt
    )
) else (
    echo   [OK] CrewAI 已安装（分镜 4-Agent 矩阵可用）
)

:: ── Step 5: 启动（源码运行默认网页版，浏览器打开）──
echo.
echo [5/5] 启动应用（网页版）...
echo.

python "%~dp0start.py"

if %errorlevel% neq 0 (
    echo.
    echo   [WARN] 启动失败，请检查上方错误信息。
    echo   也可手动运行: python start.py
    echo.
)

pause
