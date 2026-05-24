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
感謝您的訊息！
很抱歉，婚禮報報📣僅供資訊公告，無法逐一回覆訊息。
如有其他需求，歡迎以電話或個人 LINE 直接與新人聯繫噢！
謝謝您 😊
婚禮相關資訊請點選下方「婚禮小幫手」 👇"""


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
