"""
handlers/ceremony.py — 婚禮儀節表 handler
從 Firestore settings/main 取得 ceremony_images 陣列，回傳可左右滑動的 Image Carousel
點擊圖片會在瀏覽器開啟原圖
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


async def handle_ceremony(
    line_bot_api: AsyncMessagingApi,
    reply_token: str,
    context: Mapping[str, Any] | None = None,
) -> None:
    """
    處理「婚禮儀節表」Postback 事件
    從 Firestore 讀取 ceremony_images（URL 陣列），組成 Image Carousel 回傳
    向下相容：若 ceremony_images 不存在，fallback 至舊的 ceremony_image_url 字串
    """
    reply_context = {**(context or {}), "handler": "ceremony"}
    logger.info("進入 ceremony handler %s", format_log_context(reply_context))

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

        # 優先讀取新的陣列欄位，向下相容舊的字串欄位
        image_urls: list[str] = data.get("ceremony_images", [])
        if not image_urls:
            old_url = data.get("ceremony_image_url", "")
            if old_url:
                image_urls = [old_url]

        if not image_urls:
            logger.warning(
                "ceremony_images 與 ceremony_image_url 欄位皆為空 %s",
                format_log_context(reply_context),
            )
            await _reply_error(line_bot_api, reply_token, reply_context)
            return

        # 每張圖片組成一個 column；點擊圖片開啟原圖 URL
        columns = [
            ImageCarouselColumn(
                image_url=url,
                action=URIAction(
                    label="查看儀節表",   # 最多 20 字
                    uri=url,
                ),
            )
            for url in image_urls
        ]

        await safe_reply_message(
            line_bot_api,
            reply_token=reply_token,
            messages=[
                TemplateMessage(
                    alt_text="婚禮儀節表",   # 不支援 template 的環境顯示此文字
                    template=ImageCarouselTemplate(columns=columns),
                )
            ],
            context={**reply_context, "image_count": len(columns)},
        )
        logger.info(
            "ceremony handler 執行完成 image_count=%d %s",
            len(columns),
            format_log_context(reply_context),
        )

    except Exception:
        logger.exception("handle_ceremony 發生錯誤 %s", format_log_context(reply_context))
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
        messages=[TextMessage(text="抱歉，目前無法取得儀節表，請洽詢現場工作人員 🙏")],
        context={**(context or {}), "handler": "ceremony_error"},
    )
