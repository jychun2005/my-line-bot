import os
import re
import time
import requests
import subprocess
import threading
import logging
from dotenv import load_dotenv

os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler("logs/auto_start.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("auto_start")

# 忽略 SSL 警告
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 載入環境變數
load_dotenv(override=True)
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")

def update_line_webhook(url):
    logger.info(f"[系統] 偵測到全新的 Cloudflare 網址: {url}")
    logger.info("[系統] 正在自動為您更新 LINE Webhook 設定...")
    
    webhook_endpoint = f"{url}/line/webhook"
    api_url = "https://api.line.me/v2/bot/channel/webhook/endpoint"
    headers = {
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "endpoint": webhook_endpoint
    }
    
    max_retries = 5
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.put(api_url, headers=headers, json=data, verify=False)
            if response.status_code == 200:
                logger.info(f"[系統] ✅ LINE Webhook 自動更新成功！現在您的機器人已經可以正常接收訊息了！")
                return True
            else:
                logger.error(f"[系統] ❌ LINE Webhook 更新失敗 (嘗試 {attempt}/{max_retries}): {response.status_code} - {response.text}")
                if attempt < max_retries:
                    logger.info("[系統] 等待 3 秒後重試...")
                    time.sleep(3)
        except Exception as e:
            logger.error(f"[系統] ❌ LINE Webhook 更新發生錯誤 (嘗試 {attempt}/{max_retries}): {e}")
            if attempt < max_retries:
                logger.info("[系統] 等待 3 秒後重試...")
                time.sleep(3)
                
    logger.error("[系統] ❌ LINE Webhook 更新最終失敗，請嘗試手動至 LINE Developers 後台更新。")
    return False

def start_cloudflared():
    # 尋找已安裝的 cloudflared 執行檔
    cloudflared_path = None
    packages_dir = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages")
    if os.path.exists(packages_dir):
        for root, dirs, files in os.walk(packages_dir):
            if "cloudflared.exe" in files:
                cloudflared_path = os.path.join(root, "cloudflared.exe")
                break
                
    if not cloudflared_path:
        logger.error("[系統] ❌ 找不到 cloudflared.exe！請確定已透過 winget 安裝。")
        return

    logger.info("[系統] 正在啟動 Cloudflare 網路通道...")
    # 啟動 cloudflared
    process = subprocess.Popen(
        [cloudflared_path, "tunnel", "--url", "http://127.0.0.1:8646"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding='utf-8',
        errors='replace'
    )
    
    url_pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
    webhook_updated = False
    
    # 即時讀取輸出並尋找網址
    for line in iter(process.stdout.readline, ''):
        stripped = line.strip()
        print(f"[通道] {stripped}")
        if stripped:
            logger.info(f"[通道] {stripped}")
        if not webhook_updated:
            match = url_pattern.search(line)
            if match:
                new_url = match.group(0)
                # 等待 2 秒確保通道穩定
                time.sleep(2)
                update_line_webhook(new_url)
                webhook_updated = True

def start_fastapi():
    print("[系統] 正在啟動 AI 伺服器...")
    # 啟動 main.py (FastAPI)
    venv_python = os.path.join("venv", "Scripts", "python.exe")
    if not os.path.exists(venv_python):
        venv_python = "python" # fallback
        
    subprocess.Popen(
        [venv_python, "main.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

if __name__ == "__main__":
    print("========================================")
    print("      LINE AI 機器人全自動啟動程式      ")
    print("========================================")
    
    # 啟動 FastAPI 伺服器
    threading.Thread(target=start_fastapi, daemon=True).start()
    
    # 啟動 Cloudflared 並監聽網址
    start_cloudflared()
