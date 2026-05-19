@echo off
chcp 65001 >nul 2>&1
title AI Toolkit
python "%~dp0start.py"
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Failed to start.
    pause
)
