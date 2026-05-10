"""
richmenu/setup_richmenu.py — Rich Menu 一次性設定腳本
手動執行一次即可：python richmenu/setup_richmenu.py

執行流程：
1. 建立 Rich Menu（定義版面與 action）
2. 上傳 Rich Menu 圖片（richmenu/richmenu.png）
3. 設為預設 Rich Menu
4. 印出 Rich Menu ID 供確認
"""

import io
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from PIL import Image
from linebot.v3.messaging import (
    ApiClient,
    MessagingApi,
    MessagingApiBlob,
    Configuration,
    RichMenuRequest,
    RichMenuSize,
    RichMenuArea,
    RichMenuBounds,
    PostbackAction,
    RichMenuSwitchAction,
)

# 載入 .env 環境變數（腳本從專案根目錄執行）
load_dotenv()

ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
if not ACCESS_TOKEN:
    print("錯誤：請先設定 LINE_CHANNEL_ACCESS_TOKEN 環境變數")
    sys.exit(1)

# Rich Menu 圖片路徑（相對於 setup_richmenu.py 所在目錄）
SCRIPT_DIR = Path(__file__).parent
RICHMENU_IMAGE_PATH = SCRIPT_DIR / "richmenu.png"

# Rich Menu 尺寸：2500 x 1686（LINE 建議尺寸）
MENU_WIDTH = 2500
MENU_HEIGHT = 1686

# 每個格子的寬/高（2欄 x 2列）
CELL_W = MENU_WIDTH // 2   # 1250
CELL_H = MENU_HEIGHT // 2  # 843


def create_rich_menu() -> str:
    """
    建立 Rich Menu 並回傳 rich_menu_id
    版面：左上(婚禮儀節表)、右上(婚宴桌號查詢)、左下(教會婚禮資訊)、右下(婚宴飯店資訊)
    """
    config = Configuration(access_token=ACCESS_TOKEN)

    with ApiClient(config) as api_client:
        line_bot_api = MessagingApi(api_client)

        rich_menu_request = RichMenuRequest(
            size=RichMenuSize(width=MENU_WIDTH, height=MENU_HEIGHT),
            selected=True,           # 預設展開 Rich Menu
            name="婚禮小幫手選單",
            chat_bar_text="婚禮小幫手 🎊",
            areas=[
                # 左上：婚禮儀節表
                RichMenuArea(
                    bounds=RichMenuBounds(
                        x=0, y=0, width=CELL_W, height=CELL_H
                    ),
                    action=PostbackAction(
                        label="婚禮儀節表",
                        data="action=ceremony",
                        display_text="查看婚禮儀節表",
                    ),
                ),
                # 右上：婚宴桌號查詢
                RichMenuArea(
                    bounds=RichMenuBounds(
                        x=CELL_W, y=0, width=CELL_W, height=CELL_H
                    ),
                    action=PostbackAction(
                        label="婚宴桌號查詢",
                        data="action=seat_start",
                        display_text="桌號查詢",
                    ),
                ),
                # 左下：教會婚禮資訊
                RichMenuArea(
                    bounds=RichMenuBounds(
                        x=0, y=CELL_H, width=CELL_W, height=CELL_H
                    ),
                    action=PostbackAction(
                        label="教會婚禮資訊",
                        data="action=church",
                        display_text="查看教會婚禮資訊",
                    ),
                ),
                # 右下：婚宴飯店資訊
                RichMenuArea(
                    bounds=RichMenuBounds(
                        x=CELL_W, y=CELL_H, width=CELL_W, height=CELL_H
                    ),
                    action=PostbackAction(
                        label="婚宴飯店資訊",
                        data="action=venue",
                        display_text="查看婚宴飯店資訊",
                    ),
                ),
            ],
        )

        response = line_bot_api.create_rich_menu(rich_menu_request)
        rich_menu_id = response.rich_menu_id
        print(f"✅ Rich Menu 建立成功！ID：{rich_menu_id}")
        return rich_menu_id


COMPRESSED_PATH = Path("/tmp/richmenu_compressed.jpg")
MAX_SIZE_BYTES = 1 * 1024 * 1024  # LINE 上限 1MB


def compress_image() -> Path:
    """
    將 richmenu.png 壓縮至 1MB 以下，存成暫存 JPEG 檔。
    從 quality=85 開始，每次降 5，直到檔案小於 1MB。
    回傳壓縮後的暫存檔路徑。
    """
    original_size = RICHMENU_IMAGE_PATH.stat().st_size
    print(f"📦 原始圖片大小：{original_size / 1024 / 1024:.2f} MB")

    img = Image.open(RICHMENU_IMAGE_PATH).convert("RGB")

    # 強制 resize 至 LINE 要求的 Rich Menu 尺寸（必須與 RichMenuSize 完全一致）
    if img.size != (MENU_WIDTH, MENU_HEIGHT):
        print(f"   原始尺寸 {img.size} → resize 至 {MENU_WIDTH}x{MENU_HEIGHT}")
        img = img.resize((MENU_WIDTH, MENU_HEIGHT), Image.LANCZOS)

    quality = 85
    while quality >= 10:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        size = buf.tell()
        print(f"   quality={quality} → {size / 1024:.0f} KB")

        if size <= MAX_SIZE_BYTES:
            # 寫入暫存檔
            COMPRESSED_PATH.write_bytes(buf.getvalue())
            print(f"✅ 壓縮完成：{size / 1024:.0f} KB（quality={quality}）")
            return COMPRESSED_PATH

        quality -= 5

    raise RuntimeError("無法將圖片壓縮至 1MB 以下，請先縮小圖片尺寸再試")


def upload_rich_menu_image(rich_menu_id: str) -> None:
    """壓縮圖片後上傳至 LINE，上傳完成後刪除暫存檔"""
    if not RICHMENU_IMAGE_PATH.exists():
        print(f"⚠️  找不到圖片檔案：{RICHMENU_IMAGE_PATH}")
        print("請將 Rich Menu 圖片放置於 richmenu/richmenu.png 後重新執行")
        return

    # 壓縮圖片至 1MB 以下
    compressed_path = compress_image()

    config = Configuration(access_token=ACCESS_TOKEN)

    try:
        with ApiClient(config) as api_client:
            blob_api = MessagingApiBlob(api_client)
            image_data = compressed_path.read_bytes()

            blob_api.set_rich_menu_image(
                rich_menu_id=rich_menu_id,
                body=image_data,
                _headers={"Content-Type": "image/jpeg"},
            )
            print("✅ Rich Menu 圖片上傳成功！")
    finally:
        # 無論成功或失敗，都刪除暫存檔
        if compressed_path.exists():
            compressed_path.unlink()
            print("🗑️  暫存檔已刪除")


def set_default_rich_menu(rich_menu_id: str) -> None:
    """將指定的 Rich Menu 設為所有使用者的預設選單"""
    config = Configuration(access_token=ACCESS_TOKEN)

    with ApiClient(config) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.set_default_rich_menu(rich_menu_id)
        print(f"✅ 已設為預設 Rich Menu！")


def main() -> None:
    print("=== 開始建立婚禮小幫手 Rich Menu ===\n")

    # Step 1：建立 Rich Menu
    rich_menu_id = create_rich_menu()

    # Step 2：上傳圖片
    upload_rich_menu_image(rich_menu_id)

    # Step 3：設為預設
    set_default_rich_menu(rich_menu_id)

    print(f"\n=== 完成！Rich Menu ID：{rich_menu_id} ===")
    print("請將此 ID 記錄下來，日後若需刪除或更換時使用。")


if __name__ == "__main__":
    main()
