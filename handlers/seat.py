"""
handlers/seat.py — 桌號查詢 handler
支援精確比對、模糊比對（rapidfuzz）、待確認流程
"""

import logging
from rapidfuzz import process as fuzz_process, fuzz

from linebot.v3.messaging import (
    AsyncMessagingApi,
    ReplyMessageRequest,
    TextMessage,
)
from db.firestore import (
    get_db,
    COLLECTION_SEATS,
    COLLECTION_USER_STATES,
)

logger = logging.getLogger(__name__)

# 相似度門檻
THRESHOLD_HIGH = 80   # >= 80：直接回傳桌號
THRESHOLD_LOW = 60    # 60~79：請使用者確認；< 60：查無此人


async def handle_seat_start(
    line_bot_api: AsyncMessagingApi, reply_token: str, user_id: str
) -> None:
    """
    處理「桌號查詢」Postback 事件
    設定 user_state 為 waiting_for_name，請使用者輸入姓名
    """
    db = get_db()

    try:
        # 寫入使用者狀態，等待輸入姓名
        await db.collection(COLLECTION_USER_STATES).document(user_id).set(
            {"state": "waiting_for_name"}
        )

        await line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text="請輸入您的姓名 🔍")],
            )
        )
        logger.info("user=%s 進入桌號查詢流程", user_id)

    except Exception as e:
        logger.error("handle_seat_start 發生錯誤：%s", e, exc_info=True)
        await line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text="抱歉，系統發生錯誤，請稍後再試 🙏")],
            )
        )


async def handle_text_message(
    line_bot_api: AsyncMessagingApi,
    reply_token: str,
    user_id: str,
    text: str,
) -> bool:
    """
    根據 user_state 決定如何處理文字訊息。
    回傳 True 表示已處理，False 表示交由 fallback 處理。
    """
    db = get_db()

    # 查詢使用者目前的狀態
    state_doc = await db.collection(COLLECTION_USER_STATES).document(user_id).get()

    if not state_doc.exists:
        # 無待處理狀態，交由 fallback 處理
        return False

    state_data = state_doc.to_dict()
    state = state_data.get("state", "")

    if state == "waiting_for_name":
        # 使用者輸入姓名，進行模糊比對
        await _search_seat(line_bot_api, reply_token, user_id, text)
        return True

    if state == "pending_confirm" and text.strip() == "是":
        # 使用者確認模糊比對結果
        await _confirm_seat(line_bot_api, reply_token, user_id, state_data)
        return True

    if state == "pending_confirm":
        # 使用者回覆了其他內容，視為重新輸入姓名
        await db.collection(COLLECTION_USER_STATES).document(user_id).set(
            {"state": "waiting_for_name"}
        )
        await _search_seat(line_bot_api, reply_token, user_id, text)
        return True

    return False


async def _search_seat(
    line_bot_api: AsyncMessagingApi,
    reply_token: str,
    user_id: str,
    name_input: str,
) -> None:
    """
    執行桌號模糊比對核心邏輯
    1. 從 Firestore seats collection 撈出所有賓客資料
    2. 用 rapidfuzz 做模糊比對
    3. 依相似度門檻回傳對應訊息
    """
    db = get_db()
    query_name = name_input.strip()  # 去除前後空白

    try:
        # 撈出所有賓客座位資料
        seats_docs = db.collection(COLLECTION_SEATS).stream()
        seats = []
        async for doc in seats_docs:
            seat_data = doc.to_dict()
            raw_name = seat_data.get("name", "").strip()  # 資料庫名字也 strip
            if raw_name:
                seats.append({
                    "name": raw_name,
                    "table": seat_data.get("table_id"),
                    "table_name": seat_data.get("table_name", ""),
                })

        if not seats:
            logger.warning("seats collection 為空")
            await _reply_text(
                line_bot_api,
                reply_token,
                "目前尚未設定座位資料，請洽詢現場工作人員 🙏",
            )
            await db.collection(COLLECTION_USER_STATES).document(user_id).delete()
            return

        # 建立名字列表供 rapidfuzz 比對
        name_list = [s["name"] for s in seats]
        result = fuzz_process.extractOne(
            query_name, name_list, scorer=fuzz.WRatio
        )

        if result is None:
            await _reply_not_found(line_bot_api, reply_token)
            await db.collection(COLLECTION_USER_STATES).document(user_id).delete()
            return

        matched_name, score, index = result
        matched_table = seats[index]["table"]
        matched_table_name = seats[index].get("table_name", "")

        logger.info(
            "模糊比對：輸入=%s, 比對結果=%s, 相似度=%s, 桌號=%s",
            query_name, matched_name, score, matched_table,
        )

        if score >= THRESHOLD_HIGH:
            # 高相似度：直接回傳桌號
            table_display = f"「{matched_table_name}」第 {matched_table} 桌" if matched_table_name else f"第 {matched_table} 桌"
            await _reply_text(
                line_bot_api,
                reply_token,
                f"找到了！{matched_name} 的座位是{table_display} 🎉",
            )
            # 查詢完成，清除使用者狀態
            await db.collection(COLLECTION_USER_STATES).document(user_id).delete()

        elif score >= THRESHOLD_LOW:
            # 中等相似度：請使用者確認
            await db.collection(COLLECTION_USER_STATES).document(user_id).set(
                {
                    "state": "pending_confirm",
                    "pending_name": matched_name,
                    "pending_table": matched_table,
                    "pending_table_name": matched_table_name,
                }
            )
            await _reply_text(
                line_bot_api,
                reply_token,
                f"您是指 {matched_name} 嗎？\n請回覆「是」確認，或重新輸入姓名",
            )

        else:
            # 低相似度：查無此人
            await _reply_not_found(line_bot_api, reply_token)
            await db.collection(COLLECTION_USER_STATES).document(user_id).delete()

    except Exception as e:
        logger.error("_search_seat 發生錯誤：%s", e, exc_info=True)
        await _reply_text(
            line_bot_api, reply_token, "查詢時發生錯誤，請稍後再試 🙏"
        )
        await db.collection(COLLECTION_USER_STATES).document(user_id).delete()


async def _confirm_seat(
    line_bot_api: AsyncMessagingApi,
    reply_token: str,
    user_id: str,
    state_data: dict,
) -> None:
    """
    使用者確認模糊比對結果，回傳暫存的桌號並清除狀態
    """
    db = get_db()
    pending_name = state_data.get("pending_name", "")
    pending_table = state_data.get("pending_table", "")
    pending_table_name = state_data.get("pending_table_name", "")

    table_display = f"「{pending_table_name}」第 {pending_table} 桌" if pending_table_name else f"第 {pending_table} 桌"
    await _reply_text(
        line_bot_api,
        reply_token,
        f"找到了！{pending_name} 的座位是{table_display} 🎉",
    )
    # 清除使用者狀態
    await db.collection(COLLECTION_USER_STATES).document(user_id).delete()
    logger.info("user=%s 確認桌號：%s 桌", user_id, pending_table)


async def _reply_not_found(
    line_bot_api: AsyncMessagingApi, reply_token: str
) -> None:
    """查無此姓名時的回覆"""
    await _reply_text(
        line_bot_api,
        reply_token,
        "查無此姓名，請確認後再試，或洽詢現場工作人員 🙏",
    )


async def _reply_text(
    line_bot_api: AsyncMessagingApi, reply_token: str, text: str
) -> None:
    """輔助函式：回傳單一文字訊息"""
    await line_bot_api.reply_message(
        ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(text=text)],
        )
    )
