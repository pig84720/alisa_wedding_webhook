"""
handlers/venue.py — 婚宴會館資訊 handler
從 Firestore settings/main 取得會館名稱、地址、地圖連結，組成文字訊息回傳
"""

import logging
from linebot.v3.messaging import (
    AsyncMessagingApi,
    ReplyMessageRequest,
    TextMessage,
)
from db.firestore import get_db, COLLECTION_SETTINGS, DOC_MAIN

logger = logging.getLogger(__name__)


async def handle_venue(line_bot_api: AsyncMessagingApi, reply_token: str) -> None:
    """
    處理「婚宴會館資訊」Postback 事件
    從 Firestore 取得 venue_name、venue_address、venue_map_url，組成文字訊息回傳
    """
    db = get_db()

    try:
        # 從 settings/main 文件取得會館資訊
        doc_ref = db.collection(COLLECTION_SETTINGS).document(DOC_MAIN)
        doc = await doc_ref.get()

        if not doc.exists:
            logger.warning("Firestore settings/main 文件不存在")
            await _reply_error(line_bot_api, reply_token)
            return

        data = doc.to_dict()
        venue_name = data.get("venue_name", "")
        venue_address = data.get("venue_address", "")
        venue_map_url = data.get("venue_map_url", "")

        # 組合回覆訊息
        lines = ["🏛️ 婚宴會館資訊"]
        if venue_name:
            lines.append(f"📍 {venue_name}")
        if venue_address:
            lines.append(f"🗺️ 地址：{venue_address}")
        if venue_map_url:
            lines.append(f"🔗 地圖：{venue_map_url}")

        if len(lines) == 1:
            # 沒有任何資料
            logger.warning("venue 相關欄位皆為空")
            await _reply_error(line_bot_api, reply_token)
            return

        message_text = "\n".join(lines)

        await line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=message_text)],
            )
        )
        logger.info("已回傳婚宴會館資訊：%s", venue_name)

    except Exception as e:
        logger.error("handle_venue 發生錯誤：%s", e, exc_info=True)
        await _reply_error(line_bot_api, reply_token)


async def _reply_error(line_bot_api: AsyncMessagingApi, reply_token: str) -> None:
    """回傳通用錯誤訊息"""
    await line_bot_api.reply_message(
        ReplyMessageRequest(
            reply_token=reply_token,
            messages=[
                TextMessage(text="抱歉，目前無法取得會館資訊，請洽詢現場工作人員 🙏")
            ],
        )
    )
