"""
handlers/fallback.py — 罐頭訊息 handler
當使用者傳送無法辨識的訊息時，回傳使用說明
"""

import logging
from linebot.v3.messaging import (
    AsyncMessagingApi,
    ReplyMessageRequest,
    TextMessage,
)

logger = logging.getLogger(__name__)

FALLBACK_MESSAGE = """\
👋 歡迎使用婚禮小幫手！
請使用下方選單操作：
📋 儀節表 — 查看典禮流程
🪑 桌號查詢 — 輸入姓名找座位
🏛️ 婚宴會館資訊 — 地址與地圖
🎮 小遊戲 — 一起來玩 Kahoot！"""


async def handle_fallback(line_bot_api: AsyncMessagingApi, reply_token: str) -> None:
    """
    回傳罐頭訊息，引導使用者使用 Rich Menu
    """
    try:
        await line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=FALLBACK_MESSAGE)],
            )
        )
        logger.info("已回傳罐頭訊息")
    except Exception as e:
        logger.error("handle_fallback 發生錯誤：%s", e, exc_info=True)
