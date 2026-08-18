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

:: ── Step 4: 可选依赖检测 ──
echo.
echo [4/5] 检测可选依赖...
python -c "import crewai" >nul 2>&1
if %errorlevel% neq 0 (
    echo   [INFO] CrewAI 未安装 — 分镜工作台功能不可用
    echo          如需使用，请运行: pip install crewai langchain-openai
) else (
    echo   [OK] CrewAI 已安装（分镜工作台可用）
)

:: ── Step 5: 检测端口并启动 ──
echo.
echo [5/5] 启动桌面应用...
echo.

python "%~dp0desktop_app.py"

if %errorlevel% neq 0 (
    echo.
    echo   [WARN] 桌面窗口启动失败，尝试用浏览器模式启动...
    echo   请检查上方错误信息，或尝试手动运行:
    echo   python start.py --browser
    echo.
    python "%~dp0start.py" --browser
)

pause
