"""
richmenu/setup_richmenu.py — Rich Menu 一次性設定腳本
手動執行一次即可：python richmenu/setup_richmenu.py

執行流程：
1. 建立 Rich Menu（定義版面與 action）
2. 上傳 Rich Menu 圖片（richmenu/richmenu.png）
3. 設為預設 Rich Menu
4. 印出 Rich Menu ID 供確認
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
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
    版面：左上(儀節表)、右上(桌號查詢)、左下(婚宴資訊)、右下(小遊戲)
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
                # 左上：儀節表
                RichMenuArea(
                    bounds=RichMenuBounds(
                        x=0, y=0, width=CELL_W, height=CELL_H
                    ),
                    action=PostbackAction(
                        label="📋 儀節表",
                        data="action=ceremony",
                        display_text="查看儀節表",
                    ),
                ),
                # 右上：桌號查詢
                RichMenuArea(
                    bounds=RichMenuBounds(
                        x=CELL_W, y=0, width=CELL_W, height=CELL_H
                    ),
                    action=PostbackAction(
                        label="🪑 桌號查詢",
                        data="action=seat_start",
                        display_text="桌號查詢",
                    ),
                ),
                # 左下：婚宴會館資訊
                RichMenuArea(
                    bounds=RichMenuBounds(
                        x=0, y=CELL_H, width=CELL_W, height=CELL_H
                    ),
                    action=PostbackAction(
                        label="🏛️ 婚宴會館資訊",
                        data="action=venue",
                        display_text="婚宴會館資訊",
                    ),
                ),
                # 右下：小遊戲
                RichMenuArea(
                    bounds=RichMenuBounds(
                        x=CELL_W, y=CELL_H, width=CELL_W, height=CELL_H
                    ),
                    action=PostbackAction(
                        label="🎮 小遊戲",
                        data="action=game",
                        display_text="小遊戲",
                    ),
                ),
            ],
        )

        response = line_bot_api.create_rich_menu(rich_menu_request)
        rich_menu_id = response.rich_menu_id
        print(f"✅ Rich Menu 建立成功！ID：{rich_menu_id}")
        return rich_menu_id


def upload_rich_menu_image(rich_menu_id: str) -> None:
    """上傳 Rich Menu 圖片（需為 PNG 或 JPEG，建議尺寸 2500x1686）"""
    if not RICHMENU_IMAGE_PATH.exists():
        print(f"⚠️  找不到圖片檔案：{RICHMENU_IMAGE_PATH}")
        print("請將 Rich Menu 圖片放置於 richmenu/richmenu.png 後重新執行")
        return

    config = Configuration(access_token=ACCESS_TOKEN)

    with ApiClient(config) as api_client:
        blob_api = MessagingApiBlob(api_client)

        with open(RICHMENU_IMAGE_PATH, "rb") as f:
            image_data = f.read()

        blob_api.set_rich_menu_image(
            rich_menu_id=rich_menu_id,
            body=image_data,
            _headers={"Content-Type": "image/png"},
        )
        print(f"✅ Rich Menu 圖片上傳成功！")


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
