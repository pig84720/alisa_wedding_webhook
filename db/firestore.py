"""
db/firestore.py — Firestore AsyncClient 管理
提供全域 client 實例，以及 init/close 生命週期函式
"""

import os
import logging
from google.cloud.firestore_v1.async_client import AsyncClient

logger = logging.getLogger(__name__)

# 全域 AsyncClient，由 lifespan 初始化後供各 handler 使用
_db: AsyncClient | None = None


async def init_firestore() -> None:
    """
    初始化 Firestore AsyncClient。
    GOOGLE_APPLICATION_CREDENTIALS 環境變數需指向 serviceAccount.json 路徑。
    """
    global _db
    credentials_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if credentials_path:
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path

    _db = AsyncClient()
    logger.info("Firestore AsyncClient 建立完成")


async def close_firestore() -> None:
    """關閉 Firestore 連線，釋放資源"""
    global _db
    if _db is not None:
        _db.close()
        _db = None
        logger.info("Firestore AsyncClient 已關閉")


def get_db() -> AsyncClient:
    """取得全域 Firestore AsyncClient，若未初始化則拋出例外"""
    if _db is None:
        raise RuntimeError("Firestore AsyncClient 尚未初始化，請先呼叫 init_firestore()")
    return _db


# ── 常用集合名稱常數 ──────────────────────────────────────────
COLLECTION_SETTINGS = "settings"
DOC_MAIN = "main"
COLLECTION_SEATS = "seats"
COLLECTION_USER_STATES = "user_states"
