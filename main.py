"""
main.py — FastAPI 應用程式入口
負責初始化 LINE Bot client、設定 Webhook 端點、分派事件
"""

import asyncio
import os
import logging
import inspect
import secrets
import time
from contextlib import asynccontextmanager
from typing import Literal

import aiohttp
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException, Header, Query
from fastapi.responses import JSONResponse

from linebot.v3 import WebhookParser
from linebot.v3.messaging import (
    AsyncApiClient,
    AsyncMessagingApi,
    Configuration,
)
from linebot.v3.webhooks import (
    MessageEvent,
    PostbackEvent,
    TextMessageContent,
)
from linebot.v3.exceptions import InvalidSignatureError

from db.firestore import (
    init_firestore,
    close_firestore,
    get_db,
    COLLECTION_SETTINGS,
    DOC_MAIN,
    COLLECTION_SEATS,
)
from handlers.ceremony import handle_ceremony
from handlers.church import handle_church
from handlers.seat import (
    find_best_seat_match,
    handle_seat_start,
    handle_text_message,
    refresh_seat_cache,
    warm_seat_cache,
)
from handlers.venue import handle_venue
from handlers.fallback import handle_fallback
from utils.line_reply import format_log_context, sanitize_log_context

# 載入 .env 環境變數
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)



# 延遲初始化：在 lifespan 內建立，避免模組載入時無 event loop
_api_client: AsyncApiClient | None = None
line_bot_api: AsyncMessagingApi | None = None
_diagnostic_session: aiohttp.ClientSession | None = None
OUTBOUND_DIAGNOSTIC_TARGETS = [
    "https://api.line.me",
    "https://www.google.com",
    "https://www.microsoft.com",
]
OUTBOUND_DIAGNOSTIC_TIMEOUT_SECONDS = 5
DEFAULT_LOAD_TEST_QUERY_NAME = "王小明"

# Webhook 簽名驗證解析器（同步，無 event loop 需求）
parser = WebhookParser(os.environ["LINE_CHANNEL_SECRET"])


@asynccontextmanager
async def lifespan(app: FastAPI):
    """應用程式生命週期管理：啟動時初始化 Firestore 與 LINE client，關閉時釋放連線"""
    global _api_client, line_bot_api, _diagnostic_session

    # 初始化 LINE Messaging API client（需要在 event loop 內）
    _line_config = Configuration(
        access_token=os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
    )
    _api_client = AsyncApiClient(_line_config)
    line_bot_api = AsyncMessagingApi(_api_client)
    app.state.line_bot_api = line_bot_api
    logger.info("LINE AsyncApiClient 已初始化 pid=%s", os.getpid())

    _diagnostic_session = aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=OUTBOUND_DIAGNOSTIC_TIMEOUT_SECONDS),
        trust_env=True,
    )
    app.state.diagnostic_session = _diagnostic_session
    logger.info("diagnostic aiohttp session 已初始化 pid=%s", os.getpid())

    await init_firestore()
    logger.info("Firestore AsyncClient 已初始化 pid=%s", os.getpid())
    await warm_seat_cache()

    yield

    await close_firestore()
    logger.info("Firestore AsyncClient 已關閉 pid=%s", os.getpid())

    if _diagnostic_session is not None and not _diagnostic_session.closed:
        await _diagnostic_session.close()
        logger.info("diagnostic aiohttp session 已關閉 pid=%s", os.getpid())
    _diagnostic_session = None

    if _api_client is not None:
        close_method = getattr(_api_client, "close", None)
        if callable(close_method):
            close_result = close_method()
            if inspect.isawaitable(close_result):
                await close_result
        else:
            await _api_client.__aexit__(None, None, None)
        logger.info("LINE AsyncApiClient 已關閉 pid=%s", os.getpid())
    _api_client = None
    line_bot_api = None


app = FastAPI(title="婚禮小幫手 Webhook", lifespan=lifespan)


def _require_line_bot_api() -> AsyncMessagingApi:
    if line_bot_api is None:
        raise RuntimeError("LINE AsyncMessagingApi 尚未初始化")
    return line_bot_api


def _event_context(event, *, handler: str, text: str | None = None, postback_data: str | None = None) -> dict:
    context = {
        "handler": handler,
        "event_type": event.__class__.__name__,
        "event_id": getattr(event, "webhook_event_id", None),
        "user_id": getattr(getattr(event, "source", None), "user_id", None),
        "reply_token": getattr(event, "reply_token", None),
    }
    if text is not None:
        context["text"] = text
    if postback_data is not None:
        context["postback_data"] = postback_data
    return sanitize_log_context(context)


def _require_diagnostic_token(provided_token: str | None) -> None:
    configured_token = os.environ.get("DIAGNOSTIC_TOKEN", "").strip()
    if not configured_token:
        logger.warning("outbound diagnostic 被呼叫，但 DIAGNOSTIC_TOKEN 未設定")
        raise HTTPException(status_code=503, detail="Diagnostic endpoint not configured")
    if not provided_token or not secrets.compare_digest(provided_token, configured_token):
        logger.warning("outbound diagnostic token 驗證失敗")
        raise HTTPException(status_code=403, detail="Forbidden")


async def _probe_outbound_target(
    session: aiohttp.ClientSession,
    target_url: str,
    timeout_seconds: float = OUTBOUND_DIAGNOSTIC_TIMEOUT_SECONDS,
) -> dict:
    started_at = time.monotonic()
    try:
        async with session.get(
            target_url,
            timeout=aiohttp.ClientTimeout(total=timeout_seconds),
            allow_redirects=False,
        ) as response:
            elapsed_ms = (time.monotonic() - started_at) * 1000
            return {
                "target": target_url,
                "success": True,
                "status_code": response.status,
                "elapsed_ms": round(elapsed_ms, 1),
                "error_type": None,
                "error_message": None,
            }
    except Exception as exc:
        elapsed_ms = (time.monotonic() - started_at) * 1000
        return {
            "target": target_url,
            "success": False,
            "status_code": None,
            "elapsed_ms": round(elapsed_ms, 1),
            "error_type": type(exc).__name__,
            "error_message": str(exc) or repr(exc),
        }


async def _run_load_probe(
    scenario: Literal["settings_read", "seat_lookup"],
    query_name: str,
) -> dict:
    """執行單次內部壓測探針，不觸發真實 LINE Reply API。"""
    db = get_db()
    started_at = time.monotonic()

    if scenario == "settings_read":
        doc = await db.collection(COLLECTION_SETTINGS).document(DOC_MAIN).get()
        elapsed_ms = (time.monotonic() - started_at) * 1000
        return {
            "scenario": scenario,
            "success": True,
            "elapsed_ms": round(elapsed_ms, 1),
            "document_exists": doc.exists,
            "documents_scanned": 1,
            "best_score": None,
            "pid": os.getpid(),
        }

    match_result = await find_best_seat_match(query_name)

    elapsed_ms = (time.monotonic() - started_at) * 1000
    return {
        "scenario": scenario,
        "success": True,
        "elapsed_ms": round(elapsed_ms, 1),
        "document_exists": None,
        "documents_scanned": 0 if match_result is None else match_result.documents_scanned,
        "best_score": None if match_result is None else round(match_result.best_score, 1),
        "pid": os.getpid(),
    }


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

    logger.info("收到 webhook event_count=%d", len(events))

    for event in events:
        event_context = _event_context(event, handler="webhook_dispatch")
        try:
            if isinstance(event, PostbackEvent):
                await _dispatch_postback(event)
            elif isinstance(event, MessageEvent) and isinstance(
                event.message, TextMessageContent
            ):
                await _dispatch_message(event)
            else:
                logger.info("略過未處理事件 %s", format_log_context(event_context))
                continue
            logger.info("Webhook event 處理完成 %s", format_log_context(event_context))
        except Exception as e:
            logger.error(
                "處理事件時發生錯誤：%s %s",
                e,
                format_log_context(event_context),
                exc_info=True,
            )

    return JSONResponse(content={"status": "ok"})


async def _dispatch_postback(event: PostbackEvent):
    """
    處理 Postback 事件，根據 data 欄位分派至對應 handler
    """
    data = event.postback.data  # 例如 "action=ceremony"
    user_id = event.source.user_id
    reply_token = event.reply_token
    context = _event_context(
        event,
        handler="postback_dispatch",
        postback_data=data,
    )
    logger.info("進入 Postback 處理 %s", format_log_context(context))
    api = _require_line_bot_api()

    if data == "action=ceremony":
        await handle_ceremony(api, reply_token, context)
    elif data == "action=seat_start":
        await handle_seat_start(api, reply_token, user_id, context)
    elif data == "action=church":
        await handle_church(api, reply_token, context)
    elif data == "action=venue":
        await handle_venue(api, reply_token, context)
    else:
        await handle_fallback(api, reply_token, context)
    logger.info("Postback 處理完成 %s", format_log_context(context))


async def _dispatch_message(event: MessageEvent):
    """
    處理文字訊息事件
    先查詢使用者狀態，再決定要執行桌號查詢或回傳罐頭訊息
    """
    user_id = event.source.user_id
    reply_token = event.reply_token
    text = event.message.text.strip()
    context = _event_context(
        event,
        handler="message_dispatch",
        text=text,
    )
    logger.info("進入文字訊息處理 %s", format_log_context(context))
    api = _require_line_bot_api()

    # 將文字訊息路由至 seat handler（內部會判斷 user_state）
    handled = await handle_text_message(api, reply_token, user_id, text, context)

    # 若 seat handler 未處理，回傳罐頭訊息
    if not handled:
        logger.info("文字訊息未命中 seat handler，轉交 fallback %s", format_log_context(context))
        await handle_fallback(api, reply_token, context)

    logger.info("文字訊息處理完成 handled=%s %s", handled, format_log_context(context))


@app.get("/health")
async def health_check():
    """健康檢查端點"""
    return {"status": "ok"}


@app.get("/internal/diagnostics/outbound")
async def outbound_diagnostics(
    request: Request,
    diagnostic_token: str | None = Header(default=None, alias="X-Diagnostic-Token"),
):
    """測試 App Service 對外連線能力，僅供內部診斷使用。"""
    _require_diagnostic_token(diagnostic_token)

    session = getattr(request.app.state, "diagnostic_session", None)
    if session is None or session.closed:
        raise HTTPException(status_code=503, detail="Diagnostic session not available")

    results = await asyncio.gather(
        *[
            _probe_outbound_target(session, target_url)
            for target_url in OUTBOUND_DIAGNOSTIC_TARGETS
        ]
    )

    logger.info(
        "outbound diagnostics 完成 success_count=%d total=%d",
        sum(1 for result in results if result["success"]),
        len(results),
    )
    return {
        "status": "ok",
        "results": results,
    }


@app.get("/internal/diagnostics/load-probe")
async def load_probe(
    diagnostic_token: str | None = Header(default=None, alias="X-Diagnostic-Token"),
    scenario: Literal["settings_read", "seat_lookup"] = Query(default="seat_lookup"),
    query_name: str = Query(default=DEFAULT_LOAD_TEST_QUERY_NAME, min_length=1, max_length=32),
    refresh_cache: bool = Query(default=False),
):
    """
    受保護的壓測探針。
    用來模擬 App Service + Firestore 的實際負載，不會對 LINE API 發送 reply。
    """
    _require_diagnostic_token(diagnostic_token)

    if refresh_cache:
        await refresh_seat_cache(force=True)

    try:
        result = await _run_load_probe(scenario, query_name.strip())
    except Exception as exc:
        logger.exception("load probe 執行失敗 scenario=%s", scenario)
        raise HTTPException(
            status_code=500,
            detail={
                "scenario": scenario,
                "error_type": type(exc).__name__,
                "error_message": str(exc) or repr(exc),
            },
        ) from exc

    logger.info(
        "load probe 完成 scenario=%s elapsed_ms=%.1f documents_scanned=%s pid=%s",
        result["scenario"],
        result["elapsed_ms"],
        result["documents_scanned"],
        result["pid"],
    )
    return {
        "status": "ok",
        "result": result,
    }
