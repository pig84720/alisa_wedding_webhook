"""
handlers/ceremony.py — 婚禮儀節表 handler
從 Firestore settings/main 取得 ceremony_images 陣列，回傳可左右滑動的 Image Carousel
點擊圖片會在瀏覽器開啟原圖
"""

import logging
from datetime import datetime, timezone, timedelta
from linebot.v3.messaging import (
    AsyncMessagingApi,
    ReplyMessageRequest,
    TemplateMessage,
    ImageCarouselTemplate,
    ImageCarouselColumn,
    URIAction,
    TextMessage,
)
from db.firestore import get_db, COLLECTION_SETTINGS, DOC_MAIN

logger = logging.getLogger(__name__)

# 台灣時區 (UTC+8)
_TW = timezone(timedelta(hours=8))
# 功能開放日期：2026/06/20 00:00 台灣時間
RELEASE_DATE = datetime(2026, 6, 20, tzinfo=_TW)
NOT_YET_MSG = "婚禮儀節表及桌位資訊將於婚禮前一週陸續開放查詢，感謝您的耐心等候，期待與您共享這份喜悅。"


async def handle_ceremony(line_bot_api: AsyncMessagingApi, reply_token: str) -> None:
    """
    處理「婚禮儀節表」Postback 事件
    從 Firestore 讀取 ceremony_images（URL 陣列），組成 Image Carousel 回傳
    向下相容：若 ceremony_images 不存在，fallback 至舊的 ceremony_image_url 字串
    """
    # 開放日期前回傳提示訊息
    if datetime.now(tz=_TW) < RELEASE_DATE:
        await line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=NOT_YET_MSG)],
            )
        )
        return

    db = get_db()

    try:
        doc = await db.collection(COLLECTION_SETTINGS).document(DOC_MAIN).get()

        if not doc.exists:
            logger.warning("Firestore settings/main 文件不存在")
            await _reply_error(line_bot_api, reply_token)
            return

        data = doc.to_dict()

        # 優先讀取新的陣列欄位，向下相容舊的字串欄位
        image_urls: list[str] = data.get("ceremony_images", [])
        if not image_urls:
            old_url = data.get("ceremony_image_url", "")
            if old_url:
                image_urls = [old_url]

        if not image_urls:
            logger.warning("ceremony_images 與 ceremony_image_url 欄位皆為空")
            await _reply_error(line_bot_api, reply_token)
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

        await line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[
                    TemplateMessage(
                        alt_text="婚禮儀節表",   # 不支援 template 的環境顯示此文字
                        template=ImageCarouselTemplate(columns=columns),
                    )
                ],
            )
        )
        logger.info("已回傳儀節表 carousel，共 %d 張圖", len(columns))

    except Exception as e:
        logger.error("handle_ceremony 發生錯誤：%s", e, exc_info=True)
        await _reply_error(line_bot_api, reply_token)


async def _reply_error(line_bot_api: AsyncMessagingApi, reply_token: str) -> None:
    """回傳通用錯誤訊息"""
    await line_bot_api.reply_message(
        ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(text="抱歉，目前無法取得儀節表，請洽詢現場工作人員 🙏")],
        )
    )
