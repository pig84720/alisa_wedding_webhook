"""
handlers/game.py — 小遊戲 handler
從 Firestore settings/main 取得 Kahoot 連結，回傳含連結的文字訊息
"""

import logging
from linebot.v3.messaging import (
    AsyncMessagingApi,
    ReplyMessageRequest,
    TextMessage,
)
from db.firestore import get_db, COLLECTION_SETTINGS, DOC_MAIN

logger = logging.getLogger(__name__)


async def handle_game(line_bot_api: AsyncMessagingApi, reply_token: str) -> None:
    """
    處理「小遊戲」Postback 事件
    從 Firestore 取得 kahoot_url，回傳含連結的文字訊息
    """
    db = get_db()

    try:
        # 從 settings/main 文件取得 Kahoot 連結
        doc_ref = db.collection(COLLECTION_SETTINGS).document(DOC_MAIN)
        doc = await doc_ref.get()

        if not doc.exists:
            logger.warning("Firestore settings/main 文件不存在")
            await _reply_error(line_bot_api, reply_token)
            return

        data = doc.to_dict()
        kahoot_url = data.get("kahoot_url", "")

        if not kahoot_url:
            logger.warning("kahoot_url 欄位為空")
            await _reply_error(line_bot_api, reply_token)
            return

        message_text = f"🎮 一起來玩 Kahoot！\n點擊下方連結加入遊戲：\n{kahoot_url}"

        await line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=message_text)],
            )
        )
        logger.info("已回傳 Kahoot 連結")

    except Exception as e:
        logger.error("handle_game 發生錯誤：%s", e, exc_info=True)
        await _reply_error(line_bot_api, reply_token)


async def _reply_error(line_bot_api: AsyncMessagingApi, reply_token: str) -> None:
    """回傳通用錯誤訊息"""
    await line_bot_api.reply_message(
        ReplyMessageRequest(
            reply_token=reply_token,
            messages=[
                TextMessage(text="抱歉，目前無法取得遊戲連結，請洽詢現場工作人員 🙏")
            ],
        )
    )
