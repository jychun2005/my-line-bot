@echo off
chcp 65001 >nul
color 0A
echo ==========================================
echo        正在啟動 LINE AI 機器人系統...
echo ==========================================
cd /d "c:\2026Antigravity2\0705hermestoagy"
call venv\Scripts\activate.bat
python auto_start.py
pause
