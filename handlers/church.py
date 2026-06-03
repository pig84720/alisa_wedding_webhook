"""
handlers/church.py — 教會婚禮資訊 handler
從 Firestore settings/main 取得 church_images 陣列與 church_map_url
回傳可左右滑動的 Image Carousel，點擊圖片導向 Google Maps
"""

import logging
from typing import Any, Mapping

from linebot.v3.messaging import (
    AsyncMessagingApi,
    TemplateMessage,
    ImageCarouselTemplate,
    ImageCarouselColumn,
    URIAction,
    TextMessage,
)
from db.firestore import get_db, COLLECTION_SETTINGS, DOC_MAIN
from utils.line_reply import format_log_context, safe_reply_message

logger = logging.getLogger(__name__)


async def handle_church(
    line_bot_api: AsyncMessagingApi,
    reply_token: str,
    context: Mapping[str, Any] | None = None,
) -> None:
    """
    處理「教會婚禮資訊」Postback 事件
    從 Firestore 讀取 church_images（URL 陣列）與 church_map_url
    每張圖點擊後導向 Google Maps
    """
    reply_context = {**(context or {}), "handler": "church"}
    logger.info("進入 church handler %s", format_log_context(reply_context))
    db = get_db()

    try:
        doc = await db.collection(COLLECTION_SETTINGS).document(DOC_MAIN).get()

        if not doc.exists:
            logger.warning(
                "Firestore settings/main 文件不存在 %s",
                format_log_context(reply_context),
            )
            await _reply_error(line_bot_api, reply_token, reply_context)
            return

        data = doc.to_dict()
        image_urls: list[str] = data.get("church_images", [])
        map_url: str = data.get("church_map_url", "")

        if not image_urls:
            logger.warning(
                "church_images 欄位為空 %s",
                format_log_context(reply_context),
            )
            await _reply_error(line_bot_api, reply_token, reply_context)
            return

        columns = [
            ImageCarouselColumn(
                image_url=url,
                action=URIAction(
                    label="查看交通資訊",
                    uri=url,
                ),
            )
            for url in image_urls
        ]

        map_url: str = data.get("church_map_url", "")
        map_text = f"📍 地圖導航\n真耶穌教會雙連教會\n{map_url}" if map_url else "📍 真耶穌教會雙連教會"

        messages = [
            TemplateMessage(
                alt_text="教會婚禮資訊",
                template=ImageCarouselTemplate(columns=columns),
            ),
            TextMessage(text=map_text),
        ]

        await safe_reply_message(
            line_bot_api,
            reply_token=reply_token,
            messages=messages,
            context={**reply_context, "image_count": len(columns)},
        )
        logger.info(
            "church handler 執行完成 image_count=%d %s",
            len(columns),
            format_log_context(reply_context),
        )

    except Exception:
        logger.exception("handle_church 發生錯誤 %s", format_log_context(reply_context))
        await _reply_error(line_bot_api, reply_token, reply_context)


async def _reply_error(
    line_bot_api: AsyncMessagingApi,
    reply_token: str,
    context: Mapping[str, Any] | None = None,
) -> None:
    """回傳通用錯誤訊息"""
    await safe_reply_message(
        line_bot_api,
        reply_token=reply_token,
        messages=[TextMessage(text="抱歉，目前無法取得教會資訊，請洽詢現場工作人員 🙏")],
        context={**(context or {}), "handler": "church_error"},
    )
