"""
main.py — FastAPI 應用程式入口
負責初始化 LINE Bot client、設定 Webhook 端點、分派事件
"""

import os
import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse

from linebot.v3 import WebhookParser
from linebot.v3.messaging import (
    AsyncApiClient,
    AsyncMessagingApi,
    Configuration,
    ReplyMessageRequest,
)
from linebot.v3.webhooks import (
    MessageEvent,
    PostbackEvent,
    TextMessageContent,
)
from linebot.v3.exceptions import InvalidSignatureError

from db.firestore import init_firestore, close_firestore
from handlers.ceremony import handle_ceremony
from handlers.church import handle_church
from handlers.seat import handle_seat_start, handle_text_message
from handlers.venue import handle_venue
from handlers.fallback import handle_fallback

# 載入 .env 環境變數
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)



# 延遲初始化：在 lifespan 內建立，避免模組載入時無 event loop
_api_client: AsyncApiClient | None = None
line_bot_api: AsyncMessagingApi | None = None

# Webhook 簽名驗證解析器（同步，無 event loop 需求）
parser = WebhookParser(os.environ["LINE_CHANNEL_SECRET"])


@asynccontextmanager
async def lifespan(app: FastAPI):
    """應用程式生命週期管理：啟動時初始化 Firestore 與 LINE client，關閉時釋放連線"""
    global _api_client, line_bot_api

    # 初始化 LINE Messaging API client（需要在 event loop 內）
    _line_config = Configuration(
        access_token=os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
    )
    _api_client = AsyncApiClient(_line_config)
    line_bot_api = AsyncMessagingApi(_api_client)
    logger.info("LINE AsyncApiClient 已初始化")

    await init_firestore()
    logger.info("Firestore AsyncClient 已初始化")

    yield

    await close_firestore()
    logger.info("Firestore AsyncClient 已關閉")

    await _api_client.__aexit__(None, None, None)
    logger.info("LINE AsyncApiClient 已關閉")


app = FastAPI(title="婚禮小幫手 Webhook", lifespan=lifespan)


@app.post("/webhook")
async def webhook(request: Request):
    """
    LINE Webhook 端點
    1. 驗證 X-Line-Signature
    2. 解析事件列表
    3. 依事件類型分派至對應 handler
    """
    signature = request.headers.get("X-Line-Signature", "")
    body = await request.body()
    body_text = body.decode("utf-8")

    # 驗證簽名，失敗回傳 400
    try:
        events = parser.parse(body_text, signature)
    except InvalidSignatureError:
        logger.warning("LINE signature 驗證失敗")
        raise HTTPException(status_code=400, detail="Invalid signature")

    for event in events:
        try:
            if isinstance(event, PostbackEvent):
                await _dispatch_postback(event)
            elif isinstance(event, MessageEvent) and isinstance(
                event.message, TextMessageContent
            ):
                await _dispatch_message(event)
        except Exception as e:
            logger.error("處理事件時發生錯誤：%s", e, exc_info=True)

    return JSONResponse(content={"status": "ok"})


async def _dispatch_postback(event: PostbackEvent):
    """
    處理 Postback 事件，根據 data 欄位分派至對應 handler
    """
    data = event.postback.data  # 例如 "action=ceremony"
    user_id = event.source.user_id
    reply_token = event.reply_token

    logger.info("Postback 事件：user=%s, data=%s", user_id, data)

    if data == "action=ceremony":
        await handle_ceremony(line_bot_api, reply_token)
    elif data == "action=seat_start":
        await handle_seat_start(line_bot_api, reply_token, user_id)
    elif data == "action=church":
        await handle_church(line_bot_api, reply_token)
    elif data == "action=venue":
        await handle_venue(line_bot_api, reply_token)
    else:
        await handle_fallback(line_bot_api, reply_token)


async def _dispatch_message(event: MessageEvent):
    """
    處理文字訊息事件
    先查詢使用者狀態，再決定要執行桌號查詢或回傳罐頭訊息
    """
    user_id = event.source.user_id
    reply_token = event.reply_token
    text = event.message.text.strip()

    logger.info("文字訊息事件：user=%s, text=%s", user_id, text)

    # 將文字訊息路由至 seat handler（內部會判斷 user_state）
    handled = await handle_text_message(line_bot_api, reply_token, user_id, text)

    # 若 seat handler 未處理，回傳罐頭訊息
    if not handled:
        await handle_fallback(line_bot_api, reply_token)


@app.get("/health")
async def health_check():
    """健康檢查端點"""
    return {"status": "healthy"}


@app.get("/debug/seats")
async def debug_seats():
    """臨時 debug 端點：確認 Firestore guests collection 是否可讀"""
    from db.firestore import get_db, COLLECTION_SEATS
    db = get_db()
    seats_docs = db.collection(COLLECTION_SEATS).stream()
    names = []
    async for doc in seats_docs:
        data = doc.to_dict()
        names.append(data.get("name", "(no name)"))
    return {"collection": COLLECTION_SEATS, "count": len(names), "sample": names[:5]}
