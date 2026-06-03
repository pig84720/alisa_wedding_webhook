"""
utils/line_reply.py — LINE Reply API 安全封裝
集中處理 timeout、retry 與結構化 logging。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Mapping, Sequence

import aiohttp
from linebot.v3.messaging import AsyncMessagingApi, ReplyMessageRequest

logger = logging.getLogger(__name__)

DEFAULT_REPLY_TIMEOUT_SECONDS = 8.0
DEFAULT_REPLY_MAX_ATTEMPTS = 3
DEFAULT_REPLY_RETRY_DELAY_SECONDS = 0.5
TEXT_PREVIEW_LIMIT = 120
SENSITIVE_LOG_KEYS = {"access_token", "channel_secret", "authorization"}
RETRYABLE_REPLY_EXCEPTIONS = (
    aiohttp.ClientConnectorError,
    aiohttp.ClientError,
    asyncio.TimeoutError,
    TimeoutError,
)


def mask_reply_token(reply_token: str | None) -> str | None:
    """只保留 reply token 前幾碼，避免完整敏感資訊進入 log。"""
    if not reply_token:
        return None
    return f"{reply_token[:8]}..."


def sanitize_log_context(context: Mapping[str, Any] | None) -> dict[str, Any]:
    """過濾與裁切 log context，避免敏感資訊外洩。"""
    if not context:
        return {}

    sanitized: dict[str, Any] = {}
    for key, value in context.items():
        if value is None:
            continue

        lowered_key = key.lower()
        if lowered_key in SENSITIVE_LOG_KEYS:
            continue

        if lowered_key == "reply_token":
            sanitized["reply_token_prefix"] = mask_reply_token(str(value))
            continue

        if isinstance(value, str):
            collapsed = value.replace("\n", "\\n").strip()
            if lowered_key in {"text", "message_text", "postback_data"}:
                if len(collapsed) > TEXT_PREVIEW_LIMIT:
                    collapsed = f"{collapsed[:TEXT_PREVIEW_LIMIT - 3]}..."
                sanitized[key] = collapsed
            else:
                sanitized[key] = collapsed
            continue

        sanitized[key] = value

    return sanitized


def format_log_context(context: Mapping[str, Any] | None) -> str:
    """將 context 格式化成容易掃描的 key=value 字串。"""
    sanitized = sanitize_log_context(context)
    if not sanitized:
        return "context=none"
    pairs = [f"{key}={value!r}" for key, value in sanitized.items()]
    return " ".join(pairs)


async def safe_reply_message(
    line_bot_api: AsyncMessagingApi,
    *,
    reply_token: str,
    messages: Sequence[Any],
    context: Mapping[str, Any] | None = None,
    timeout_seconds: float = DEFAULT_REPLY_TIMEOUT_SECONDS,
    max_attempts: int = DEFAULT_REPLY_MAX_ATTEMPTS,
    retry_delay_seconds: float = DEFAULT_REPLY_RETRY_DELAY_SECONDS,
) -> bool:
    """
    安全呼叫 LINE Reply API。

    只針對暫時性網路錯誤與 timeout 做短 retry，並輸出明確 log。
    """
    request = ReplyMessageRequest(
        reply_token=reply_token,
        messages=list(messages),
    )
    base_context = {
        **sanitize_log_context(context),
        "reply_token": reply_token,
        "message_count": len(messages),
    }
    formatted_context = format_log_context(base_context)

    for attempt in range(1, max_attempts + 1):
        started_at = time.monotonic()
        try:
            logger.info(
                "準備呼叫 LINE reply_message attempt=%d/%d timeout=%.1fs %s",
                attempt,
                max_attempts,
                timeout_seconds,
                formatted_context,
            )
            await asyncio.wait_for(
                line_bot_api.reply_message(request),
                timeout=timeout_seconds,
            )
            elapsed_ms = (time.monotonic() - started_at) * 1000
            logger.info(
                "LINE reply_message 成功 attempt=%d/%d elapsed_ms=%.1f %s",
                attempt,
                max_attempts,
                elapsed_ms,
                formatted_context,
            )
            return True
        except RETRYABLE_REPLY_EXCEPTIONS as exc:
            elapsed_ms = (time.monotonic() - started_at) * 1000
            logger.warning(
                "LINE reply_message 失敗 attempt=%d/%d elapsed_ms=%.1f error_type=%s error=%s %s",
                attempt,
                max_attempts,
                elapsed_ms,
                type(exc).__name__,
                str(exc) or repr(exc),
                formatted_context,
            )
            if attempt == max_attempts:
                logger.exception(
                    "LINE reply_message 最終失敗 attempts=%d %s",
                    max_attempts,
                    formatted_context,
                )
                return False
            await asyncio.sleep(retry_delay_seconds)
        except Exception:
            logger.exception("LINE reply_message 非預期失敗 %s", formatted_context)
            return False

    return False
