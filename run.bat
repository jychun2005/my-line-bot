@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion

echo ===================================================
echo   Google Antigravity LINE Bot Gateway (Windows)
echo ===================================================

:: 檢查是否有 .env 檔案
if not exist .env (
    echo [錯誤] 找不到 .env 檔案！
    echo 請將 .env.example 複製為 .env，並填寫您的 LINE 金鑰與 Gemini API Key 後再重新執行。
    pause
    exit /b 1
)

:: 檢查 python 是否存在
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [錯誤] 系統未安裝 Python，或未將其加入環境變數 PATH 中。
    pause
    exit /b 1
)

:: 建立虛擬環境 (如果不存在)
if not exist venv (
    echo 正在建立 Python 虛擬環境 (venv)...
    :: 優先嘗試使用 Python 3.12 以防 Python 3.14 編譯問題
    py -3.12 -m venv venv >nul 2>&1
    if !errorlevel! neq 0 (
        python -m venv venv
    )
    if !errorlevel! neq 0 (
        echo [錯誤] 建立虛擬環境失敗。
        pause
        exit /b 1
    )
)

:: 啟動虛擬環境並安裝套件
echo 正在啟動虛擬環境...
call venv\Scripts\activate.bat

echo 正在檢查並更新依賴套件...
python -m pip install --upgrade pip
pip install -r requirements.txt
if !errorlevel! neq 0 (
    echo [警告] 安裝依賴套件時可能遇到一些問題，請檢查網路連線。
)

echo ---------------------------------------------------
echo 正在啟動 FastAPI Gateway 伺服器...
echo ---------------------------------------------------
python main.py

pause
