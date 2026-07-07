import os
import glob
import json
import logging
import ssl
from threading import Lock
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, ImageMessage
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
        if isinstance(event, MessageEvent) and isinstance(event.message, (TextMessage, ImageMessage)):
            # 丟到背景任務，讓主程式可以秒回 200 OK 給 LINE
            background_tasks.add_task(process_and_reply, event)
            
    return "OK"

# 全域變數用來儲存使用者的短期記憶 (字典)
user_chats = {}

async def process_and_reply(event):
    user_id = event.source.user_id
    try:
        import google.generativeai as genai
        import io
        from PIL import Image
        global user_chats
        
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not set")
            
        genai.configure(api_key=api_key)
        
        # 1. 賦予專屬秘書個性
        model = genai.GenerativeModel(
            'gemini-2.5-flash-lite',
            system_instruction="你現在是一位名叫「小雅」的專屬私人秘書。你的語氣要溫柔、體貼且專業，會在適當的地方加上 Emoji。回答盡量簡潔扼要，處處為老闆（使用者）著想。若老闆傳送圖片，請發揮秘書的觀察力詳細解說。"
        )
        
        # 2. 處理短期記憶
        if user_id not in user_chats:
            user_chats[user_id] = model.start_chat(history=[])
        chat = user_chats[user_id]
        
        # 3. 判斷是文字還是圖片
        if isinstance(event.message, TextMessage):
            user_message = event.message.text
            logger.info(f"Received text message: {user_message} from user {user_id}")
            response = chat.send_message(user_message)
            
        elif isinstance(event.message, ImageMessage):
            logger.info(f"Received image message from user {user_id}")
            # 從 LINE 下載圖片內容
            message_content = line_bot_api.get_message_content(event.message.id)
            image_bytes = b""
            for chunk in message_content.iter_content():
                image_bytes += chunk
                
            image = Image.open(io.BytesIO(image_bytes))
            prompt = "老闆傳來了一張圖片，請幫我看看這張圖片的內容是什麼，並用小雅秘書的口吻向老闆報告。"
            response = chat.send_message([prompt, image])
        
        try:
            response_text = response.text
        except ValueError:
            response_text = "老闆抱歉，這則訊息被安全機制擋下來了🥺"

        # 4. 使用 Push API 回傳給 LINE
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
