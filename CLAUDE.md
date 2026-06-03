# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## 1. 專案概述

本專案是一個 **LINE 婚禮小幫手 Chatbot** 的 FastAPI 後端。

主要功能：
- **儀節表**：回傳典禮流程圖片
- **桌號查詢**：賓客輸入姓名，用模糊比對找座位（含待確認流程）
- **婚宴會館資訊**：回傳場地名稱、地址、地圖連結
- **Rich Menu**：LINE 對話底部 2×2 快捷選單

技術架構：FastAPI（async）+ LINE Bot SDK v3 + Google Cloud Firestore（AsyncClient）+ rapidfuzz 模糊比對

---

## 2. 技術規格

**Python 版本：3.12+**（3.9 會有 `X | None` 語法錯誤，且 Google SDK 不再支援）

**套件（requirements.txt）：**
```
fastapi>=0.111.0
uvicorn[standard]>=0.29.0
gunicorn>=22.0.0
line-bot-sdk>=3.11.0          # 使用 linebot.v3 命名空間
google-cloud-firestore>=2.16.0
rapidfuzz>=3.9.0
python-dotenv>=1.0.1
Pillow>=10.0.0                # Rich Menu 圖片壓縮用
```

**環境變數（.env）：**
| 變數名稱 | 說明 |
|----------|------|
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Messaging API Channel Access Token |
| `LINE_CHANNEL_SECRET` | LINE Channel Secret（Webhook 簽名驗證用） |
| `GOOGLE_APPLICATION_CREDENTIALS` | GCP 服務帳戶金鑰路徑，預設 `./serviceAccount.json` |

---

## 3. 專案結構

```
.
├── main.py                    # FastAPI 入口：初始化 LINE client、Webhook 端點、事件分派
├── db/
│   └── firestore.py           # Firestore AsyncClient 生命週期管理（init/close/get_db）
├── handlers/
│   ├── ceremony.py            # 儀節表：從 Firestore 取圖片 URL，回傳 ImageMessage
│   ├── seat.py                # 桌號查詢：rapidfuzz 模糊比對 + user_states 狀態機
│   ├── venue.py               # 婚宴會館資訊：組合文字訊息回傳
│   └── fallback.py            # 罐頭訊息：未識別輸入時引導使用選單
├── richmenu/
│   ├── richmenu.png           # Rich Menu 圖片原始檔（可超過 1MB，腳本會自動壓縮）
│   └── setup_richmenu.py      # 一次性腳本：建立 Rich Menu、壓縮上傳圖片、設為預設
├── tools/
│   ├── init_firestore.py      # 一次性腳本：寫入 settings/main 初始資料
│   └── import_seats.py        # 批次匯入 seats.csv → Firestore seats collection
├── startup.sh                 # 正式環境啟動指令（gunicorn + uvicorn worker）
├── .env.example               # 環境變數範本
└── serviceAccount.json        # GCP 服務帳戶金鑰（不可 commit）
```

---

## 4. 核心功能說明

### Webhook 處理流程（main.py）

```
POST /webhook
  ├── 驗證 X-Line-Signature（失敗 → 400）
  ├── PostbackEvent
  │   ├── action=ceremony   → handle_ceremony
  │   ├── action=seat_start → handle_seat_start（寫入 user_state: waiting_for_name）
  │   ├── action=venue      → handle_venue
  │   └── 其他             → handle_fallback
  └── MessageEvent（TextMessage）
      └── handle_text_message → 依 user_state 路由
          ├── 有 state        → seat handler 處理，回傳 True
          └── 無 state        → 回傳 False → handle_fallback
```

LINE client（`AsyncMessagingApi`）在 `main.py` 模組層級初始化，傳入各 handler 函式。Firestore AsyncClient 透過 FastAPI `lifespan` 管理，由 `db/firestore.py` 的 `get_db()` 全域取用。

### 座位查詢狀態機（handlers/seat.py）

```
[任意狀態] ──按 Rich Menu「桌號查詢」──→ waiting_for_name
                                          ↓ 使用者輸入姓名
                              rapidfuzz.WRatio 比對
                         ┌────────────────────────────┐
                    ≥ 80 │ 直接回傳桌號，刪除 state   │
                    60~79│ 寫入 pending_confirm        │──→ 使用者回「是」→ 回傳桌號，刪除 state
                     < 60│ 查無此人，刪除 state        │    使用者回其他 → 視為重新輸入姓名
                         └────────────────────────────┘
```

**比對細節：**
- 使用 `fuzz.WRatio`（加權比對，對部分匹配較友善）
- 比對前對輸入和資料庫名字都執行 `.strip()`
- `THRESHOLD_HIGH = 80`，`THRESHOLD_LOW = 60`

### user_states Firestore 文件結構

```
user_states/{LINE_user_id}
  state: "waiting_for_name" | "pending_confirm"
  pending_name: string    # 僅 pending_confirm 時存在
  pending_table: number   # 僅 pending_confirm 時存在
```

查詢完成或放棄後，文件以 `.delete()` 清除。

---

## 5. Firestore 資料結構

```
settings/main
  ceremony_image_url: string   # 儀節表圖片公開 URL（Imgur 或其他 CDN）
  venue_name: string           # 場地名稱，例："彭園三重館"
  venue_address: string        # 地址，例："新北市三重區龍門路6號3F"
  venue_map_url: string        # Google Maps 連結

seats/{auto_id}
  name: string                 # 賓客姓名
  table: number                # 桌號（整數）

user_states/{LINE_user_id}
  state: string                # "waiting_for_name" | "pending_confirm"
  pending_name: string         # 模糊比對暫存名字
  pending_table: number        # 模糊比對暫存桌號
```

**注意：** `settings/main` 文件 ID 固定為 `main`，所有 handler 都從這個文件讀取設定，欄位空白時回傳錯誤訊息而非崩潰。

---

## 6. Rich Menu 規格

| 屬性 | 值 |
|------|-----|
| 尺寸 | 2500 × 1686 px |
| 版面 | 2欄 × 2列（各 1250 × 843） |
| 格子數 | 4 |

| 位置 | 功能 | Postback data |
|------|------|---------------|
| 左上 | 📋 儀節表 | `action=ceremony` |
| 右上 | 🪑 桌號查詢 | `action=seat_start` |
| 左下 | 🏛️ 婚宴會館資訊 | `action=venue` |
| 右下 | ⛪ 教會婚禮資訊 | `action=church` |

**圖片壓縮流程（`setup_richmenu.py`）：**
1. 用 Pillow 開啟 `richmenu/richmenu.png`，強制 resize 到 2500×1686（LINE 要求圖片尺寸必須與 RichMenuSize 完全一致）
2. 轉為 RGB（去除透明通道）
3. 從 JPEG quality=85 開始，每次降 5，直到檔案 < 1MB
4. 存為 `/tmp/richmenu_compressed.jpg`，上傳後刪除暫存檔
5. Content-Type 為 `image/jpeg`

---

## 7. 部署說明（Azure App Service）

1. 在 Azure App Service 建立 Linux Python 3.12 應用程式
2. **環境變數**（設定 → 應用程式設定）：
   - `LINE_CHANNEL_ACCESS_TOKEN`
   - `LINE_CHANNEL_SECRET`
   - `GOOGLE_APPLICATION_CREDENTIALS`：填入 `/home/site/wwwroot/serviceAccount.json`
3. 將 `serviceAccount.json` 部署到專案根目錄
4. **啟動命令**設定為：
   ```
   bash startup.sh
   ```
   或直接填入：
   ```
   gunicorn -w 2 -k uvicorn.workers.UvicornWorker main:app --bind 0.0.0.0:8000
   ```
5. LINE Developers Console → Messaging API → Webhook URL 填入：
   ```
   https://your-app.azurewebsites.net/webhook
   ```
6. 開啟「使用 Webhook」，關閉「自動回覆訊息」與「加入好友的歡迎訊息」

---

## 8. 工具腳本

### `tools/init_firestore.py`（執行一次）
```bash
python tools/init_firestore.py
```
寫入 `settings/main` 初始資料（若已存在則覆蓋）。`venue_name` / `venue_address` 已預填，`ceremony_image_url`、`venue_map_url` 需事後到 Firebase Console 手動填入。

### `tools/import_seats.py`（每次更新座位時執行）
```bash
python tools/import_seats.py seats.csv
```
- 執行前會**清空** `seats` collection 再重新匯入
- CSV 格式：第一行必須是 `name,table`，支援 Excel 存出的 UTF-8 BOM（`utf-8-sig`）
- `table` 欄位必須為整數，空白列和格式錯誤列會被略過並列出警告

### `richmenu/setup_richmenu.py`（執行一次，更換圖片時重新執行）
```bash
cd /path/to/project
python richmenu/setup_richmenu.py
```
**注意：** 必須從專案根目錄執行（`load_dotenv()` 從當前目錄找 `.env`）。執行前確認 `richmenu/richmenu.png` 存在。

---

## 9. 本地開發流程

```bash
# 建立虛擬環境（需 Python 3.12）
/opt/homebrew/bin/python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 設定環境變數
cp .env.example .env
# 填入 LINE_CHANNEL_ACCESS_TOKEN 和 LINE_CHANNEL_SECRET

# 初始化 Firestore 資料（第一次）
python tools/init_firestore.py

# 啟動本地伺服器
uvicorn main:app --reload --port 8000

# 另開 Terminal，啟動 ngrok
ngrok http 8000
```

取得 ngrok URL（如 `https://xxxx.ngrok-free.app`）後，填入 LINE Developers Console：
- **Webhook URL**：`https://xxxx.ngrok-free.app/webhook`
- 開啟「使用 Webhook」

健康檢查端點：`GET /health` → `{"status": "ok"}`

---

## 10. 注意事項與常見問題

### LINE 官方帳號設定
必須在 LINE Official Account Manager 關閉：
- **自動回覆訊息**（否則 Bot 和自動回覆會同時觸發）
- **加入好友的歡迎訊息**（可選）

必須開啟：
- **Webhook**

### Rich Menu 圖片限制
- 檔案大小 **≤ 1MB**（`setup_richmenu.py` 已自動處理）
- 圖片像素尺寸**必須與 `RichMenuSize` 完全一致**（腳本自動 resize 到 2500×1686）
- 上傳格式為 JPEG（`Content-Type: image/jpeg`）

### 儀節表圖片托管
Firebase Storage 需付費方案。建議使用 [Imgur](https://imgur.com/upload) 免費上傳取得公開 URL，填入 Firestore `settings/main.ceremony_image_url`。URL 需為可直接存取的圖片連結（LINE 會直接 fetch）。

### Firestore AsyncClient
- `db/firestore.py` 維護全域 `AsyncClient` 實例 `_db`
- 所有 handler 透過 `get_db()` 取用，**不可在 handler 內自行建立新 client**
- `tools/` 下的腳本使用同步 `firestore.Client()`（非 async），兩者不可混用

### Python 版本
必須使用 **Python 3.12+**。Python 3.9 不支援 `X | None` 型別語法（PEP 604），且 Google SDK 已不再支援 3.9。
