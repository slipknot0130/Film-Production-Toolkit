@echo off
chcp 65001 >nul 2>&1
title AI Toolkit
python "%~dp0desktop_app.py"
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] 桌面程序启动失败，正在尝试用浏览器模式启动...
    python "%~dp0start.py" --browser
    if %errorlevel% neq 0 (
        echo.
        echo [ERROR] 浏览器模式也启动失败。
        pause
    )
)
