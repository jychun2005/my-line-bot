# Google Antigravity (Agy) LINE Bot Gateway (Windows)

此專案是將 Google Antigravity (Agy) Agent 串接至 LINE Bot 的 Windows 橋接服務。藉由 FastAPI 的 BackgroundTasks（非同步背景任務）機制，防止 LINE Webhook 超過 5 秒未回應而產生的逾時 (Timeout) 錯誤。

---

## 🚀 快速開始步驟

### 第一步：環境變數設定
1. 在專案根目錄下，將 `.env.example` 複製一份並命名為 `.env`：
   ```cmd
   copy .env.example .env
   ```
2. 使用文字編輯器開啟 `.env`，填入您的 LINE Bot 金鑰與 Gemini API Key：
   * **LINE_CHANNEL_ACCESS_TOKEN**：LINE Developer 後台的 Messaging API 標籤頁最下方發行。
   * **LINE_CHANNEL_SECRET**：LINE Developer 後台的 Basic Settings 最下方取得。
   * **GEMINI_API_KEY**：[Google AI Studio](https://aistudio.google.com/) 申請的 API Key。

### 第二步：安裝與啟動
1. 雙擊執行根目錄底下的 `run.bat` 檔案。
2. 批次檔會自動為您：
   * 建立 Python 虛擬環境 (`venv`)。
   * 安裝所需的依賴套件（FastAPI, Uvicorn, LINE SDK, Antigravity 等）。
   * 啟動本地端伺服器（預設監聽 `http://127.0.0.1:8646`）。

---

## 🌐 Windows 上的 Cloudflare Tunnel (網域穿透) 設定

為了讓外部的 LINE 伺服器能將 Webhook 推送到您本機的 `localhost:8646`，建議使用 Cloudflare Named Tunnel 作為免費且穩定的固定網域通道。

### 1. 安裝 cloudflared
在 Windows 上，您可以使用 `winget` 快速安裝（或至 Cloudflare 官網下載 MSI 安裝檔）：
```cmd
winget install Cloudflare.cloudflared
```

### 2. 登入並建立 Tunnel
開啟命令提示字元 (cmd) 執行：
```cmd
# 登入 Cloudflare 帳戶 (會引導開啟瀏覽器)
cloudflared tunnel login

# 建立名為 agy-line 的通道
cloudflared tunnel create agy-line
```
執行後會產生一個 **Tunnel ID**，憑證 JSON 檔會儲存於 `C:\Users\<您的使用者名稱>\.cloudflared\<Tunnel_ID>.json`。

### 3. 設定 DNS 路由
將您的個人網域（例如 `bot.yourdomain.com`）指向該 Tunnel：
```cmd
cloudflared tunnel route dns agy-line bot.yourdomain.com
```

### 4. 設定 config.yml 轉發規則
在 `C:\Users\<您的使用者名稱>\.cloudflared\` 目錄下建立一個 `config.yml` 檔案，內容填寫如下：
```yaml
tunnel: <您的_TUNNEL_ID>
credentials-file: C:\Users\<您的使用者名稱>\.cloudflared\<您的_TUNNEL_ID>.json

ingress:
  - hostname: bot.yourdomain.com
    service: http://localhost:8646
  - service: http_status:404
```

### 5. 將 Cloudflare Tunnel 註冊為 Windows 系統服務 (開機自啟動)
以**系統管理員權限**開啟命令提示字元，執行：
```cmd
# 安裝為 Windows 服務
cloudflared service install

# 啟動服務
net start cloudflared
```
如此一來，即使您的電腦重啟，Cloudflare 通道也會在背景自動連線，不需手動開啟視窗。

---

## ⏰ 設定 FastAPI 伺服器開機自動啟動

您可以透過以下兩種方式在 Windows 上達到開機自動啟動 `run.bat`：

### 方法一：放入 Windows 啟動資料夾 (最簡單)
1. 按下鍵盤 `Win + R` 鍵，輸入 `shell:startup`，然後點選「確定」，會開啟您的「啟動」資料夾。
2. 對著專案目錄下的 `run.bat` 按右鍵，選擇「建立捷徑」。
3. 將產生的 `run.bat - 捷徑` 剪下並貼入剛才開啟的「啟動」資料夾中。
4. 當您登入 Windows 後，系統會自動在背景彈出視窗啟動該服務。

### 方法二：使用「工作排程器」(適於背景完全隱藏執行)
1. 開啟「工作排程器」(Task Scheduler)。
2. 點擊右側「建立基本工作...」。
3. 名稱輸入 `Antigravity Line Gateway`。
4. 觸發程序選擇「當電腦啟動時」或「當我登入時」。
5. 動作選擇「啟動程式」，程式或指令碼欄位點選「瀏覽」，選擇本專案的 `run.bat`。
6. 「開始位置」欄位請務必填入本專案的根目錄路徑（例如 `c:\2026Antigravity2\0705hermestoagy`）。
7. 完成後，即可在背景靜默運作，避免桌面上一直留有 cmd 視窗。

---

## 🛠️ 常見問題與自我排查 (Troubleshooting)

### 1. LINE 機器人完全沒有回應
* **檢查連接埠 8646 是否正常監聽**：
  在 cmd 中執行：
  ```cmd
  netstat -ano | findstr 8646
  ```
  應可看到處於 `LISTENING` 狀態的行程。
* **檢查 Cloudflare Tunnel 狀態**：
  在瀏覽器登入 Cloudflare Dashboard 檢查 Tunnel 是否為 Active。
* **檢查日誌輸出**：
  查看專案目錄下的 `logs\gateway.log`，了解錯誤原因。

### 2. 對話中斷或報錯 `Failed to create agent: conversation "..." not found`
* **原因**：本地對應表 `sessions.json` 與 `conversations/` 目錄下的 `.db` 對話資料庫產生不同步。
* **解決方案**：直接刪除專案根目錄下的 `sessions.json` 檔案。伺服器會在下一次收到訊息時，自動判定為新對話並重新建立與綁定，即可正常聊天。
