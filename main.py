import os
import glob
import json
import logging
import ssl
from threading import Lock
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from dotenv import load_dotenv

# 全域停用 SSL 憑證驗證 (解決 Windows 上 linebot push_message 的 CERTIFICATE_VERIFY_FAILED 錯誤)
ssl._create_default_https_context = ssl._create_unverified_context

load_dotenv(override=True)

import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
original_post = requests.post
def patched_post(*args, **kwargs):
    kwargs['verify'] = False
    return original_post(*args, **kwargs)
requests.post = patched_post

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
PORT = int(os.getenv("PORT", 8646))

# 使用專案當前目錄下的相對路徑以相容 Windows / macOS
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SAVE_DIR = os.path.join(BASE_DIR, "conversations") # 儲存對話 SQLite 的路徑
SESSIONS_FILE = os.path.join(BASE_DIR, "sessions.json")

os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler("logs/gateway.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("antigravity-line-gateway")

app = FastAPI()

# 建立自訂的 HttpClient 以解決 Windows 上的 SSL 憑證驗證問題 ([SSL: CERTIFICATE_VERIFY_FAILED])
try:
    from linebot.http_client import RequestsHttpClient
    import urllib3
    
    # 抑制因 verify=False 產生的 InsecureRequestWarning 警告
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    custom_http_client = RequestsHttpClient()
    custom_http_client.session.verify = False
    line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN, http_client=custom_http_client)
    logger.info("Successfully initialized custom HttpClient with SSL verification disabled.")
except Exception as e:
    logger.warning(f"Failed to initialize custom HttpClient, falling back to default: {e}")
    line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)

handler = WebhookHandler(LINE_CHANNEL_SECRET)
sessions_lock = Lock()

def get_mapped_conv_id(user_id: str) -> str:
    with sessions_lock:
        if os.path.exists(SESSIONS_FILE):
            with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
                try:
                    return json.load(f).get(user_id)
                except Exception:
                    pass
    return None

def set_mapped_conv_id(user_id: str, conv_id: str):
    with sessions_lock:
        data = {}
        if os.path.exists(SESSIONS_FILE):
            with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
                try:
                    data = json.load(f)
                except Exception:
                    pass
        data[user_id] = conv_id
        with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.post("/line/webhook")
async def line_webhook(request: Request, background_tasks: BackgroundTasks):
    signature = request.headers.get("X-Line-Signature")
    if not signature:
        raise HTTPException(status_code=400, detail="Missing X-Line-Signature")
    
    body = await request.body()
    body_decoded = body.decode("utf-8")
    try:
        events = handler.parser.parse(body_decoded, signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    
    for event in events:
        if isinstance(event, MessageEvent) and isinstance(event.message, TextMessage):
            # 丟到背景任務，立即向 LINE 伺服器回傳 200 OK 避免逾時
            background_tasks.add_task(process_and_reply, event)
            
    return "OK"

async def process_and_reply(event):
    user_id = event.source.user_id
    user_message = event.message.text
    logger.info(f"Received message: {user_message} from user {user_id}")
    try:
        from google.antigravity import Agent, LocalAgentConfig
        os.makedirs(SAVE_DIR, exist_ok=True)
        mapped_id = get_mapped_conv_id(user_id)
        db_path = os.path.join(SAVE_DIR, f"{mapped_id}.db") if mapped_id else None
        
        # 1. 判斷是否有既有對話，若有則直接讀取
        if mapped_id and db_path and os.path.exists(db_path):
            logger.info(f"Resuming conversation '{mapped_id}' for user {user_id}")
            config = LocalAgentConfig(
                conversation_id=mapped_id,
                save_dir=SAVE_DIR,
                workspaces=[BASE_DIR],
                model="gemini-2.5-flash"
            )
            async with Agent(config) as agent:
                response = await agent.chat(user_message)
                response_text = await response.text()
        # 2. 若無，則為新使用者，讓 Agy 自動生成資料庫並紀錄對照關係
        else:
            logger.info(f"Creating new conversation for user {user_id}")
            pre_files = set(glob.glob(os.path.join(SAVE_DIR, "*.db")))
            config = LocalAgentConfig(
                save_dir=SAVE_DIR,
                workspaces=[BASE_DIR],
                model="gemini-2.5-flash"
            )
            async with Agent(config) as agent:
                post_files = set(glob.glob(os.path.join(SAVE_DIR, "*.db")))
                new_files = post_files - pre_files
                if new_files:
                    new_conv_id = os.path.basename(list(new_files)[0]).replace(".db", "")
                    logger.info(f"Mapped {user_id} to new conversation_id: {new_conv_id}")
                    set_mapped_conv_id(user_id, new_conv_id)
                response = await agent.chat(user_message)
                response_text = await response.text()

        # 3. 使用 Push API 將 AI Agent 回覆推送到使用者 LINE 對話中
        line_bot_api.push_message(
            user_id,
            TextSendMessage(text=response_text)
        )
        logger.info(f"Successfully replied to user {user_id}")
    except Exception as e:
        logger.exception(f"Error handling message: {e}")
        try:
            line_bot_api.push_message(
                user_id,
                TextSendMessage(text="抱歉，在處理您的請求時發生了錯誤。請稍後再試。")
            )
        except Exception as push_err:
            logger.error(f"Failed to push error message to LINE: {push_err}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, log_level="info")
