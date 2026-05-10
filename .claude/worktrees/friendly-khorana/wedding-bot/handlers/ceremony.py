"""
handlers/ceremony.py — 儀節表 handler
從 Firestore settings/main 取得典禮流程圖片 URL，回傳 ImageMessage
"""

import logging
from linebot.v3.messaging import (
    AsyncMessagingApi,
    ReplyMessageRequest,
    ImageMessage,
    TextMessage,
)
from db.firestore import get_db, COLLECTION_SETTINGS, DOC_MAIN

logger = logging.getLogger(__name__)


async def handle_ceremony(line_bot_api: AsyncMessagingApi, reply_token: str) -> None:
    """
    處理「儀節表」Postback 事件
    從 Firestore 取得 ceremony_image_url，回傳圖片訊息
    """
    db = get_db()

    try:
        # 從 settings/main 文件取得儀節表圖片 URL
        doc_ref = db.collection(COLLECTION_SETTINGS).document(DOC_MAIN)
        doc = await doc_ref.get()

        if not doc.exists:
            logger.warning("Firestore settings/main 文件不存在")
            await _reply_error(line_bot_api, reply_token)
            return

        data = doc.to_dict()
        ceremony_image_url = data.get("ceremony_image_url", "")

        if not ceremony_image_url:
            logger.warning("ceremony_image_url 欄位為空")
            await _reply_error(line_bot_api, reply_token)
            return

        # 回傳圖片訊息；previewImageUrl 使用相同 URL（LINE 要求必填）
        await line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[
                    ImageMessage(
                        original_content_url=ceremony_image_url,
                        preview_image_url=ceremony_image_url,
                    )
                ],
            )
        )
        logger.info("已回傳儀節表圖片：%s", ceremony_image_url)

    except Exception as e:
        logger.error("handle_ceremony 發生錯誤：%s", e, exc_info=True)
        await _reply_error(line_bot_api, reply_token)


async def _reply_error(line_bot_api: AsyncMessagingApi, reply_token: str) -> None:
    """回傳通用錯誤訊息"""
    await line_bot_api.reply_message(
        ReplyMessageRequest(
            reply_token=reply_token,
            messages=[
                TextMessage(text="抱歉，目前無法取得儀節表，請洽詢現場工作人員 🙏")
            ],
        )
    )
