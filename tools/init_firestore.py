"""
tools/init_firestore.py — 初始化 Firestore 基本資料（執行一次即可）

執行方式：
    cd /Users/lukedong/our_wedding_20261004_webhook
    python tools/init_firestore.py
"""

import os
import sys
from pathlib import Path

# 將專案根目錄加入 Python 路徑，確保能讀取 .env
ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))

from dotenv import load_dotenv
load_dotenv(ROOT_DIR / ".env")

from google.cloud import firestore

# 初始化同步 Firestore Client
db = firestore.Client()

# settings/main 初始資料
INITIAL_SETTINGS = {
    "ceremony_image_url": "",           # 儀節表圖片 URL（之後再填）
    "venue_name": "彭園三重館",
    "venue_address": "新北市三重區龍門路6號3F",
    "venue_map_url": "",                # 地圖連結（之後再填）
}


def main() -> None:
    print("=== 初始化 Firestore 基本資料 ===\n")

    # 寫入 settings/main 文件（若已存在則覆蓋）
    doc_ref = db.collection("settings").document("main")
    doc_ref.set(INITIAL_SETTINGS)

    print("✅ settings/main 寫入完成：")
    for key, value in INITIAL_SETTINGS.items():
        display_value = f'"{value}"' if value else '""  ← 待填入'
        print(f"   {key}: {display_value}")

    print("\n=== 完成！請記得回來填入空白欄位 ===")


if __name__ == "__main__":
    main()
