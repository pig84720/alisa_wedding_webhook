"""
handlers/seat.py — 桌號查詢 handler
支援精確比對、模糊比對（rapidfuzz + pypinyin 雙軌加權）、待確認流程

比對策略：
- 字元軌：rapidfuzz WRatio，權重 0.35
- 拼音軌：逐字音節位置對齊命中率，權重 0.65
- 最終分數 = 0.35 × char_score + 0.65 × pinyin_score
- 只有輸入字串與資料庫完全相同才直接回桌號；其餘超過閾值一律詢問確認
"""

import logging
from rapidfuzz import fuzz
from pypinyin import lazy_pinyin

from linebot.v3.messaging import (
    AsyncMessagingApi,
    ReplyMessageRequest,
    TextMessage,
    ImageMessage,
)
from db.firestore import (
    get_db,
    COLLECTION_SEATS,
    COLLECTION_USER_STATES,
)

logger = logging.getLogger(__name__)

# 確認門檻：加權分數 >= 60 → 詢問確認；< 60 → 查無此人
THRESHOLD_CONFIRM = 60

# 桌位圖片 URL（回傳桌號時一併附上）
SEAT_MAP_URL = "https://firebasestorage.googleapis.com/v0/b/alisa-wedding.firebasestorage.app/o/S__115515530.jpg?alt=media&token=ab92bda2-04a2-4cd5-b3a8-0cdb514739f3"


def _syllables(name: str) -> list[str]:
    """將中文姓名轉成音節 list，例如「王欣怡」→ ['wang', 'xin', 'yi']"""
    return lazy_pinyin(name)


def _pinyin_position_score(query: str, candidate: str) -> float:
    """
    逐字音節位置對齊比對，回傳 0～100 的分數。
    命中率 = 相同位置音節完全相等的數量 / max(兩者音節數)
    """
    q_syl = _syllables(query)
    c_syl = _syllables(candidate)
    max_len = max(len(q_syl), len(c_syl))
    if max_len == 0:
        return 0.0
    matches = sum(
        1 for i in range(min(len(q_syl), len(c_syl)))
        if q_syl[i] == c_syl[i]
    )
    return matches / max_len * 100


def _combined_score(query: str, candidate: str) -> float:
    """
    加權綜合分數：
      0.35 × WRatio（字元相似度）+ 0.65 × 逐字拼音位置命中率
    """
    score_char = fuzz.WRatio(query, candidate)
    score_pinyin = _pinyin_position_score(query, candidate)
    return 0.35 * score_char + 0.65 * score_pinyin


async def handle_seat_start(
    line_bot_api: AsyncMessagingApi, reply_token: str, user_id: str
) -> None:
    """
    處理「桌號查詢」Postback 事件
    設定 user_state 為 waiting_for_name，請使用者輸入姓名
    """
    db = get_db()

    try:
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

    state_doc = await db.collection(COLLECTION_USER_STATES).document(user_id).get()
    if not state_doc.exists:
        return False

    state_data = state_doc.to_dict()
    state = state_data.get("state", "")

    if state == "waiting_for_name":
        await _search_seat(line_bot_api, reply_token, user_id, text)
        return True

    if state == "pending_confirm" and text.strip() == "是":
        await _confirm_seat(line_bot_api, reply_token, user_id, state_data)
        return True

    if state == "pending_confirm":
        # 非「是」的回覆，視為重新輸入姓名
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
    執行桌號比對核心邏輯：
    1. 從 Firestore guests collection 撈出所有賓客資料
    2. 對每位賓客計算加權綜合分數（字元 0.35 + 拼音位置 0.65）
    3. 取最高分候選人：
       - 輸入與資料庫完全相同 → 直接回桌號
       - 分數 >= THRESHOLD_CONFIRM → 詢問確認
       - 分數 < THRESHOLD_CONFIRM → 查無此人
    """
    db = get_db()
    query_name = name_input.strip()

    try:
        seats_docs = db.collection(COLLECTION_SEATS).stream()
        seats = []
        async for doc in seats_docs:
            seat_data = doc.to_dict()
            raw_name = seat_data.get("name", "").strip()
            if raw_name:
                seats.append({
                    "name": raw_name,
                    "table": seat_data.get("table_id"),
                })

        if not seats:
            logger.warning("seats collection 為空")
            await _reply_text(
                line_bot_api, reply_token,
                "目前尚未設定座位資料，請洽詢現場工作人員 🙏",
            )
            await db.collection(COLLECTION_USER_STATES).document(user_id).delete()
            return

        # 對全部賓客計算加權分數，取最高
        best_score = -1.0
        best_index = -1
        for i, seat in enumerate(seats):
            score = _combined_score(query_name, seat["name"])
            if score > best_score:
                best_score = score
                best_index = i

        matched_name = seats[best_index]["name"]
        matched_table = seats[best_index]["table"]

        logger.info(
            "比對結果：輸入=%s, 最佳候選=%s, 綜合分數=%.1f, 桌號=%s",
            query_name, matched_name, best_score, matched_table,
        )

        # 完全精確命中：字串相同，直接回桌號
        if query_name == matched_name:
            await _reply_seat_result(
                line_bot_api, reply_token,
                f"{matched_name} 的座位 在第{matched_table}桌",
            )
            await db.collection(COLLECTION_USER_STATES).document(user_id).delete()

        elif best_score >= THRESHOLD_CONFIRM:
            # 分數夠高但不完全相同，詢問確認
            await db.collection(COLLECTION_USER_STATES).document(user_id).set(
                {
                    "state": "pending_confirm",
                    "pending_name": matched_name,
                    "pending_table": matched_table,
                }
            )
            await _reply_text(
                line_bot_api, reply_token,
                f"您是指 {matched_name} 嗎？\n請回覆「是」確認，或重新輸入姓名",
            )

        else:
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
    """使用者確認模糊比對結果，回傳暫存的桌號並清除狀態"""
    db = get_db()
    pending_name = state_data.get("pending_name", "")
    pending_table = state_data.get("pending_table", "")

    await _reply_seat_result(
        line_bot_api, reply_token,
        f"{pending_name} 的座位 在第{pending_table}桌",
    )
    await db.collection(COLLECTION_USER_STATES).document(user_id).delete()
    logger.info("user=%s 確認桌號：%s 桌", user_id, pending_table)


async def _reply_seat_result(
    line_bot_api: AsyncMessagingApi, reply_token: str, text: str
) -> None:
    """回傳桌號文字 + 桌位圖片"""
    await line_bot_api.reply_message(
        ReplyMessageRequest(
            reply_token=reply_token,
            messages=[
                TextMessage(text=text),
                ImageMessage(
                    original_content_url=SEAT_MAP_URL,
                    preview_image_url=SEAT_MAP_URL,
                ),
            ],
        )
    )


async def _reply_not_found(
    line_bot_api: AsyncMessagingApi, reply_token: str
) -> None:
    """查無此姓名時的回覆"""
    await _reply_text(
        line_bot_api, reply_token,
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
