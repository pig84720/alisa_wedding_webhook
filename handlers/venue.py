"""
handlers/venue.py — 婚宴飯店資訊 handler
從 Firestore settings/main 取得 venue_images 陣列與 venue_map_url
回傳可左右滑動的 Image Carousel，點擊圖片導向 Google Maps
"""

import logging
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


async def handle_venue(line_bot_api: AsyncMessagingApi, reply_token: str) -> None:
    """
    處理「婚宴飯店資訊」Postback 事件
    從 Firestore 讀取 venue_images（URL 陣列）與 venue_map_url
    每張圖點擊後導向 Google Maps
    """
    db = get_db()

    try:
        doc = await db.collection(COLLECTION_SETTINGS).document(DOC_MAIN).get()

        if not doc.exists:
            logger.warning("Firestore settings/main 文件不存在")
            await _reply_error(line_bot_api, reply_token)
            return

        data = doc.to_dict()
        image_urls: list[str] = data.get("venue_images", [])
        map_url: str = data.get("venue_map_url", "")

        if not image_urls:
            logger.warning("venue_images 欄位為空")
            await _reply_error(line_bot_api, reply_token)
            return

        # 每張圖片點擊後：有地圖連結就導到地圖，否則開啟圖片本身
        def make_action(url: str) -> URIAction:
            return URIAction(
                label="查看地圖",        # 最多 20 字
                uri=map_url if map_url else url,
            )

        columns = [
            ImageCarouselColumn(
                image_url=url,
                action=make_action(url),
            )
            for url in image_urls
        ]

        await line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[
                    TemplateMessage(
                        alt_text="婚宴飯店資訊",
                        template=ImageCarouselTemplate(columns=columns),
                    )
                ],
            )
        )
        logger.info("已回傳婚宴飯店資訊 carousel，共 %d 張圖", len(columns))

    except Exception as e:
        logger.error("handle_venue 發生錯誤：%s", e, exc_info=True)
        await _reply_error(line_bot_api, reply_token)


async def _reply_error(line_bot_api: AsyncMessagingApi, reply_token: str) -> None:
    """回傳通用錯誤訊息"""
    await line_bot_api.reply_message(
        ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(text="抱歉，目前無法取得飯店資訊，請洽詢現場工作人員 🙏")],
        )
    )
