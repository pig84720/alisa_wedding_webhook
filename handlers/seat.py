"""
handlers/seat.py — 桌號查詢 handler
支援精確比對、模糊比對（rapidfuzz + pypinyin 雙軌加權）、待確認流程

比對策略：
- 字元軌：rapidfuzz WRatio，權重 0.35
- 拼音軌：逐字音節位置對齊命中率，權重 0.65
- 最終分數 = 0.35 × char_score + 0.65 × pinyin_score
- 只有輸入字串與資料庫完全相同才直接回桌號；其餘超過閾值一律詢問確認
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Mapping

from rapidfuzz import fuzz
from pypinyin import lazy_pinyin

from linebot.v3.messaging import (
    AsyncMessagingApi,
    TextMessage,
    ImageMessage,
)
from db.firestore import (
    get_db,
    COLLECTION_SEATS,
    COLLECTION_USER_STATES,
)
from utils.line_reply import format_log_context, safe_reply_message

logger = logging.getLogger(__name__)

# 台灣時區 (UTC+8)
_TW = timezone(timedelta(hours=8))
# 功能開放日期：2026/06/20 00:00 台灣時間
RELEASE_DATE = datetime(2026, 6, 20, tzinfo=_TW)
NOT_YET_MSG = "桌位資訊將於婚禮前一週陸續開放查詢，感謝您的耐心等候，期待與您共享這份喜悅。"

# 確認門檻：加權分數 >= 60 → 詢問確認；< 60 → 查無此人
THRESHOLD_CONFIRM = 60

# 桌位圖片 URL（回傳桌號時一併附上）
SEAT_MAP_URL = "https://firebasestorage.googleapis.com/v0/b/alisa-wedding.firebasestorage.app/o/13F%E6%A0%BC%E8%90%8A_43T-01.jpg?alt=media&token=2b73a952-8054-47a2-8bb1-d99cb773836f"
SEAT_CACHE_TTL_SECONDS = 900
TRAILING_NOTE_PATTERN = re.compile(r"\s*[（(][^)）]*[)）]\s*$")
TRAILING_DIGITS_PATTERN = re.compile(r"\s*\d+\s*$")


@dataclass(frozen=True)
class SeatCacheEntry:
    """單筆座位快取資料。"""
    raw_name: str
    normalized_name: str
    table: int | str | None
    syllables: tuple[str, ...]


@dataclass(frozen=True)
class SeatGroup:
    """同一個正規化姓名群組的座位資料。"""
    normalized_name: str
    entries: tuple[SeatCacheEntry, ...]
    syllables: tuple[str, ...]


@dataclass(frozen=True)
class SeatMatchResult:
    """座位查詢比對結果。"""
    group: SeatGroup
    best_score: float
    documents_scanned: int


@dataclass(frozen=True)
class SeatCacheSnapshot:
    """整份座位快取快照。"""
    entries: tuple[SeatCacheEntry, ...]
    groups: tuple[SeatGroup, ...]
    exact_name_index: Mapping[str, SeatGroup]
    normalized_name_index: Mapping[str, SeatGroup]
    loaded_at: float


_seat_cache: SeatCacheSnapshot = SeatCacheSnapshot(
    entries=(),
    groups=(),
    exact_name_index={},
    normalized_name_index={},
    loaded_at=0.0,
)
_seat_cache_lock = asyncio.Lock()


def _syllables(name: str) -> list[str]:
    """將中文姓名轉成音節 list，例如「王欣怡」→ ['wang', 'xin', 'yi']"""
    return lazy_pinyin(name)


def normalize_guest_name(name: str) -> str:
    """
    將姓名正規化為查詢主名。

    處理規則：
    1. 去除前後空白與內部空白
    2. 去除尾端括號備註，例如「(素)」「（兒童椅）」
    3. 去除尾端數字，例如「許馨云1」→「許馨云」
    """
    normalized = "".join(name.strip().split())
    while True:
        removed_note = TRAILING_NOTE_PATTERN.sub("", normalized)
        removed_digits = TRAILING_DIGITS_PATTERN.sub("", removed_note)
        if removed_digits == normalized:
            break
        normalized = removed_digits.strip()
    return normalized


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


def _pinyin_position_score_from_syllables(
    query_syllables: tuple[str, ...],
    candidate_syllables: tuple[str, ...],
) -> float:
    """使用預先計算好的音節列表計算拼音位置分數。"""
    max_len = max(len(query_syllables), len(candidate_syllables))
    if max_len == 0:
        return 0.0
    matches = sum(
        1
        for index in range(min(len(query_syllables), len(candidate_syllables)))
        if query_syllables[index] == candidate_syllables[index]
    )
    return matches / max_len * 100


def _combined_score_cached(
    query_name: str,
    query_syllables: tuple[str, ...],
    group: SeatGroup,
) -> float:
    """對快取中的座位資料計算加權綜合分數。"""
    score_char = fuzz.WRatio(query_name, group.normalized_name)
    score_pinyin = _pinyin_position_score_from_syllables(
        query_syllables,
        group.syllables,
    )
    return 0.35 * score_char + 0.65 * score_pinyin


def _table_sort_key(table: int | str | None) -> tuple[int, object]:
    """讓桌號輸出順序穩定：數字桌先依數字排序，其餘依字串排序。"""
    if isinstance(table, int):
        return (0, table)

    if table in (None, ""):
        return (2, "")

    table_text = str(table)
    if table_text.isdigit():
        return (0, int(table_text))
    return (1, table_text)


def _format_table_reference(table: int | str | None) -> str:
    """將桌號格式化為可讀文字。"""
    if table in (None, ""):
        return "未安排桌次"
    return f"第{table}桌"


def _dedupe_entries(entries: tuple[SeatCacheEntry, ...]) -> tuple[SeatCacheEntry, ...]:
    """去除重複的姓名 / 桌號組合，避免重複輸出。"""
    seen: set[tuple[str, int | str | None]] = set()
    deduped: list[SeatCacheEntry] = []
    for entry in sorted(entries, key=lambda item: (_table_sort_key(item.table), item.raw_name)):
        entry_key = (entry.raw_name, entry.table)
        if entry_key in seen:
            continue
        seen.add(entry_key)
        deduped.append(entry)
    return tuple(deduped)


def _group_entries_by_table(
    entries: tuple[SeatCacheEntry, ...],
) -> list[tuple[int | str | None, tuple[SeatCacheEntry, ...]]]:
    """將座位結果依桌號分組，保留完整 Firestore 姓名。"""
    grouped: dict[int | str | None, list[SeatCacheEntry]] = {}
    for entry in _dedupe_entries(entries):
        grouped.setdefault(entry.table, []).append(entry)

    return [
        (table, tuple(grouped[table]))
        for table in sorted(grouped, key=_table_sort_key)
    ]


def format_seat_result_text(entries: tuple[SeatCacheEntry, ...]) -> str:
    """格式化桌位查詢回覆文字。"""
    grouped_entries = _group_entries_by_table(entries)
    if not grouped_entries:
        return "查無座位資訊，請洽詢現場工作人員 🙏"

    if len(grouped_entries) == 1 and len(grouped_entries[0][1]) == 1:
        table, members = grouped_entries[0]
        return f"{members[0].raw_name} 的座位 在{_format_table_reference(table)}"

    if len(grouped_entries) == 1:
        table, members = grouped_entries[0]
        joined_names = "、".join(entry.raw_name for entry in members)
        return f"以下賓客的座位都在{_format_table_reference(table)}：\n{joined_names}"

    lines = ["查到以下座位資訊："]
    for table, members in grouped_entries:
        joined_names = "、".join(entry.raw_name for entry in members)
        lines.append(f"{_format_table_reference(table)}：{joined_names}")
    return "\n".join(lines)


def format_seat_confirm_text(entries: tuple[SeatCacheEntry, ...]) -> str:
    """格式化模糊比對確認訊息，保留完整 Firestore 姓名。"""
    grouped_entries = _group_entries_by_table(entries)
    if not grouped_entries:
        return "請回覆「是」確認，或重新輸入姓名"

    if len(grouped_entries) == 1 and len(grouped_entries[0][1]) == 1:
        _, members = grouped_entries[0]
        return f"您是指 {members[0].raw_name} 嗎？\n請回覆「是」確認，或重新輸入姓名"

    lines = ["您是指以下賓客嗎？"]
    for table, members in grouped_entries:
        joined_names = "、".join(entry.raw_name for entry in members)
        lines.append(f"{_format_table_reference(table)}：{joined_names}")
    lines.append("請回覆「是」確認，或重新輸入姓名")
    return "\n".join(lines)


async def refresh_seat_cache(force: bool = False) -> SeatCacheSnapshot:
    """
    從 Firestore 重新載入座位資料到每個 worker 的記憶體中。
    force=False 時若快取仍在 TTL 內，直接重用現有資料。
    """
    global _seat_cache

    now = time.monotonic()
    if (
        not force
        and _seat_cache.entries
        and now - _seat_cache.loaded_at < SEAT_CACHE_TTL_SECONDS
    ):
        return _seat_cache

    async with _seat_cache_lock:
        now = time.monotonic()
        if (
            not force
            and _seat_cache.entries
            and now - _seat_cache.loaded_at < SEAT_CACHE_TTL_SECONDS
        ):
            return _seat_cache

        db = get_db()
        seats_docs = db.collection(COLLECTION_SEATS).stream()
        entries: list[SeatCacheEntry] = []
        group_members: dict[str, list[SeatCacheEntry]] = {}

        async for doc in seats_docs:
            seat_data = doc.to_dict()
            raw_name = seat_data.get("name", "").strip()
            if not raw_name:
                continue

            table_value = seat_data.get("table_id", seat_data.get("table"))
            normalized_name = normalize_guest_name(raw_name) or raw_name
            entry = SeatCacheEntry(
                raw_name=raw_name,
                normalized_name=normalized_name,
                table=table_value,
                syllables=tuple(_syllables(normalized_name)),
            )
            entries.append(entry)
            group_members.setdefault(normalized_name, []).append(entry)

        groups: list[SeatGroup] = []
        exact_name_index: dict[str, SeatGroup] = {}
        normalized_name_index: dict[str, SeatGroup] = {}

        for normalized_name, member_entries in group_members.items():
            ordered_member_entries = tuple(
                sorted(
                    member_entries,
                    key=lambda item: (_table_sort_key(item.table), item.raw_name),
                )
            )
            group = SeatGroup(
                normalized_name=normalized_name,
                entries=ordered_member_entries,
                syllables=ordered_member_entries[0].syllables,
            )
            groups.append(group)
            normalized_name_index[normalized_name] = group
            for entry in ordered_member_entries:
                compact_raw_name = "".join(entry.raw_name.strip().split())
                exact_name_index[compact_raw_name] = group

        _seat_cache = SeatCacheSnapshot(
            entries=tuple(entries),
            groups=tuple(groups),
            exact_name_index=exact_name_index,
            normalized_name_index=normalized_name_index,
            loaded_at=time.monotonic(),
        )
        logger.info(
            "seat cache 已刷新 entries=%d groups=%d ttl_seconds=%d",
            len(entries),
            len(groups),
            SEAT_CACHE_TTL_SECONDS,
        )
        return _seat_cache


async def warm_seat_cache() -> None:
    """在啟動時預熱座位快取，失敗時僅記錄 log，不阻止 app 啟動。"""
    try:
        await refresh_seat_cache(force=True)
    except Exception:
        logger.exception("seat cache 預熱失敗")


async def find_best_seat_match(query_name: str) -> SeatMatchResult | None:
    """從記憶體快取中尋找最佳座位候選人。"""
    snapshot = await refresh_seat_cache()
    if not snapshot.groups:
        return None

    compact_query_name = "".join(query_name.strip().split())
    exact_group = snapshot.exact_name_index.get(compact_query_name)
    if exact_group is not None:
        return SeatMatchResult(
            group=exact_group,
            best_score=100.0,
            documents_scanned=1,
        )

    normalized_query_name = normalize_guest_name(query_name) or compact_query_name
    normalized_group = snapshot.normalized_name_index.get(normalized_query_name)
    if normalized_group is not None:
        return SeatMatchResult(
            group=normalized_group,
            best_score=100.0,
            documents_scanned=len(normalized_group.entries),
        )

    query_syllables = tuple(_syllables(normalized_query_name))
    best_score = -1.0
    best_group: SeatGroup | None = None
    for group in snapshot.groups:
        score = _combined_score_cached(normalized_query_name, query_syllables, group)
        if score > best_score:
            best_score = score
            best_group = group

    if best_group is None:
        return None

    return SeatMatchResult(
        group=best_group,
        best_score=best_score,
        documents_scanned=len(snapshot.groups),
    )


async def handle_seat_start(
    line_bot_api: AsyncMessagingApi,
    reply_token: str,
    user_id: str,
    context: Mapping[str, Any] | None = None,
) -> None:
    """
    處理「桌號查詢」Postback 事件
    設定 user_state 為 waiting_for_name，請使用者輸入姓名
    """
    reply_context = {**(context or {}), "handler": "seat_start", "user_id": user_id}
    logger.info("進入 seat_start handler %s", format_log_context(reply_context))
    if datetime.now(tz=_TW) < RELEASE_DATE:
        await safe_reply_message(
            line_bot_api,
            reply_token=reply_token,
            messages=[TextMessage(text=NOT_YET_MSG)],
            context=reply_context,
        )
        return

    db = get_db()

    try:
        await db.collection(COLLECTION_USER_STATES).document(user_id).set(
            {"state": "waiting_for_name"}
        )
        await safe_reply_message(
            line_bot_api,
            reply_token=reply_token,
            messages=[TextMessage(text="請輸入您的姓名 🔍")],
            context=reply_context,
        )
        logger.info("seat_start handler 執行完成 %s", format_log_context(reply_context))

    except Exception:
        logger.exception("handle_seat_start 發生錯誤 %s", format_log_context(reply_context))
        await safe_reply_message(
            line_bot_api,
            reply_token=reply_token,
            messages=[TextMessage(text="抱歉，系統發生錯誤，請稍後再試 🙏")],
            context={**reply_context, "handler": "seat_start_error"},
        )


async def handle_text_message(
    line_bot_api: AsyncMessagingApi,
    reply_token: str,
    user_id: str,
    text: str,
    context: Mapping[str, Any] | None = None,
) -> bool:
    """
    根據 user_state 決定如何處理文字訊息。
    回傳 True 表示已處理，False 表示交由 fallback 處理。
    """
    reply_context = {
        **(context or {}),
        "handler": "seat_text_router",
        "user_id": user_id,
        "text": text,
    }
    db = get_db()

    state_doc = await db.collection(COLLECTION_USER_STATES).document(user_id).get()
    if not state_doc.exists:
        logger.info("seat_text_router 無狀態，交由 fallback %s", format_log_context(reply_context))
        return False

    state_data = state_doc.to_dict()
    state = state_data.get("state", "")
    logger.info("seat_text_router 命中狀態 state=%s %s", state, format_log_context(reply_context))

    if state == "waiting_for_name":
        await _search_seat(
            line_bot_api,
            reply_token,
            user_id,
            text,
            context=reply_context,
        )
        return True

    if state == "pending_confirm" and text.strip() == "是":
        await _confirm_seat(
            line_bot_api,
            reply_token,
            user_id,
            state_data,
            context=reply_context,
        )
        return True

    if state == "pending_confirm":
        # 非「是」的回覆，視為重新輸入姓名
        await db.collection(COLLECTION_USER_STATES).document(user_id).set(
            {"state": "waiting_for_name"}
        )
        await _search_seat(
            line_bot_api,
            reply_token,
            user_id,
            text,
            context=reply_context,
        )
        return True

    return False


async def _search_seat(
    line_bot_api: AsyncMessagingApi,
    reply_token: str,
    user_id: str,
    name_input: str,
    context: Mapping[str, Any] | None = None,
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
    reply_context = {
        **(context or {}),
        "handler": "seat_search",
        "user_id": user_id,
        "text": query_name,
    }

    try:
        match_result = await find_best_seat_match(query_name)
        if match_result is None:
            logger.warning("seats collection 為空 %s", format_log_context(reply_context))
            await _reply_text(
                line_bot_api, reply_token,
                "目前尚未設定座位資料，請洽詢現場工作人員 🙏",
                context=reply_context,
            )
            await db.collection(COLLECTION_USER_STATES).document(user_id).delete()
            return

        matched_group = match_result.group
        matched_name = matched_group.normalized_name
        matched_entries = matched_group.entries
        best_score = match_result.best_score

        logger.info(
            "座位比對結果 best_match=%s variants=%d tables=%s score=%.1f scanned=%d %s",
            matched_name,
            len(_dedupe_entries(matched_entries)),
            ",".join(
                _format_table_reference(table)
                for table, _ in _group_entries_by_table(matched_entries)
            ),
            best_score,
            match_result.documents_scanned,
            format_log_context(reply_context),
        )

        normalized_query_name = normalize_guest_name(query_name) or query_name

        # 完全精確命中：正規化後完全相同，直接回桌號
        if normalized_query_name == matched_name:
            await _reply_seat_result(
                line_bot_api, reply_token,
                format_seat_result_text(matched_entries),
                context={
                    **reply_context,
                    "matched_name": matched_name,
                    "table_count": len(_group_entries_by_table(matched_entries)),
                },
            )
            await db.collection(COLLECTION_USER_STATES).document(user_id).delete()

        elif best_score >= THRESHOLD_CONFIRM:
            # 分數夠高但不完全相同，詢問確認
            await db.collection(COLLECTION_USER_STATES).document(user_id).set(
                {
                    "state": "pending_confirm",
                    "pending_name": matched_name,
                    "pending_lookup_key": matched_name,
                }
            )
            await _reply_text(
                line_bot_api, reply_token,
                format_seat_confirm_text(matched_entries),
                context={
                    **reply_context,
                    "matched_name": matched_name,
                    "table_count": len(_group_entries_by_table(matched_entries)),
                },
            )

        else:
            await _reply_not_found(line_bot_api, reply_token, context=reply_context)
            await db.collection(COLLECTION_USER_STATES).document(user_id).delete()

    except Exception:
        logger.exception("_search_seat 發生錯誤 %s", format_log_context(reply_context))
        await _reply_text(
            line_bot_api, reply_token, "查詢時發生錯誤，請稍後再試 🙏"
            , context={**reply_context, "handler": "seat_search_error"}
        )
        await db.collection(COLLECTION_USER_STATES).document(user_id).delete()


async def _confirm_seat(
    line_bot_api: AsyncMessagingApi,
    reply_token: str,
    user_id: str,
    state_data: dict,
    context: Mapping[str, Any] | None = None,
) -> None:
    """使用者確認模糊比對結果，回傳暫存的桌號並清除狀態"""
    db = get_db()
    pending_lookup_key = state_data.get("pending_lookup_key") or state_data.get("pending_name", "")
    match_result = await find_best_seat_match(pending_lookup_key)

    if match_result is None:
        await _reply_text(
            line_bot_api,
            reply_token,
            "抱歉，座位資料剛更新，請重新查詢姓名 🔍",
            context={**(context or {}), "handler": "seat_confirm_missing_match", "user_id": user_id},
        )
        await db.collection(COLLECTION_USER_STATES).document(user_id).delete()
        return

    await _reply_seat_result(
        line_bot_api, reply_token,
        format_seat_result_text(match_result.group.entries),
        context={
            **(context or {}),
            "handler": "seat_confirm",
            "user_id": user_id,
            "matched_name": pending_lookup_key,
            "table_count": len(_group_entries_by_table(match_result.group.entries)),
        },
    )
    await db.collection(COLLECTION_USER_STATES).document(user_id).delete()
    logger.info(
        "seat_confirm handler 執行完成 user_id=%s tables=%s",
        user_id,
        ",".join(
            _format_table_reference(table)
            for table, _ in _group_entries_by_table(match_result.group.entries)
        ),
    )


async def _reply_seat_result(
    line_bot_api: AsyncMessagingApi,
    reply_token: str,
    text: str,
    context: Mapping[str, Any] | None = None,
) -> None:
    """回傳桌號文字 + 桌位圖片"""
    await safe_reply_message(
        line_bot_api,
        reply_token=reply_token,
        messages=[
            TextMessage(text=text),
            ImageMessage(
                original_content_url=SEAT_MAP_URL,
                preview_image_url=SEAT_MAP_URL,
            ),
        ],
        context=context,
    )


async def _reply_not_found(
    line_bot_api: AsyncMessagingApi,
    reply_token: str,
    context: Mapping[str, Any] | None = None,
) -> None:
    """查無此姓名時的回覆"""
    await _reply_text(
        line_bot_api, reply_token,
        "查無此姓名，請確認後再試，或洽詢現場工作人員 🙏",
        context={**(context or {}), "handler": "seat_not_found"},
    )


async def _reply_text(
    line_bot_api: AsyncMessagingApi,
    reply_token: str,
    text: str,
    context: Mapping[str, Any] | None = None,
) -> None:
    """輔助函式：回傳單一文字訊息"""
    await safe_reply_message(
        line_bot_api,
        reply_token=reply_token,
        messages=[TextMessage(text=text)],
        context=context,
    )
