"""
tools/import_seats.py — 從 CSV 批次匯入賓客座位資料到 Firestore seats collection

執行方式：
    cd /Users/lukedong/our_wedding_20261004_webhook
    python tools/import_seats.py seats.csv

CSV 格式（第一行為 header）：
    name,table
    王小明,3
    李美華,7
"""

import os
import sys
import csv
from pathlib import Path

# 將專案根目錄加入 Python 路徑，確保能讀取 .env
ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))

from dotenv import load_dotenv
load_dotenv(ROOT_DIR / ".env")

from google.cloud import firestore


def delete_collection(col_ref, batch_size: int = 100) -> None:
    """
    清空指定 collection 的所有文件
    Firestore 不支援直接刪除整個 collection，需逐批刪除
    """
    docs = col_ref.list_documents(page_size=batch_size)
    deleted = 0

    for doc in docs:
        doc.delete()
        deleted += 1

    # 若該批次剛好等於 batch_size，可能還有剩餘文件，遞迴繼續刪除
    if deleted >= batch_size:
        delete_collection(col_ref, batch_size)


def main() -> None:
    # 確認命令列有傳入 CSV 路徑
    if len(sys.argv) < 2:
        print("用法：python tools/import_seats.py <csv檔案路徑>")
        print("範例：python tools/import_seats.py seats.csv")
        sys.exit(1)

    csv_path = Path(sys.argv[1])

    # 確認 CSV 檔案存在
    if not csv_path.exists():
        print(f"錯誤：找不到檔案 {csv_path}")
        sys.exit(1)

    # 初始化同步 Firestore Client
    db = firestore.Client()
    seats_col = db.collection("seats")

    print("=== 開始匯入賓客座位資料 ===\n")

    # 清空 seats collection（匯入前先清除舊資料）
    print("🗑️  清空 seats collection 中...")
    delete_collection(seats_col)
    print("✅ 清空完成\n")

    # 讀取 CSV 並批次寫入 Firestore
    imported_count = 0
    errors = []

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        # utf-8-sig 可自動處理 Excel 存出的 BOM 字元
        reader = csv.DictReader(f)

        # 驗證 CSV 欄位名稱
        if reader.fieldnames is None or not {"name", "table"}.issubset(reader.fieldnames):
            print("錯誤：CSV 必須包含 'name' 和 'table' 兩個欄位")
            sys.exit(1)

        for row_num, row in enumerate(reader, start=2):  # start=2 因為第一行是 header
            name = row.get("name", "").strip()
            table_raw = row.get("table", "").strip()

            # 跳過空白列
            if not name and not table_raw:
                continue

            # 驗證資料完整性
            if not name:
                errors.append(f"第 {row_num} 行：name 欄位為空，已略過")
                continue

            if not table_raw:
                errors.append(f"第 {row_num} 行（{name}）：table 欄位為空，已略過")
                continue

            # 驗證 table 為數字
            try:
                table = int(table_raw)
            except ValueError:
                errors.append(f"第 {row_num} 行（{name}）：table 值 '{table_raw}' 不是有效數字，已略過")
                continue

            # 寫入 Firestore，使用自動產生的 doc ID
            seats_col.add({"name": name, "table": table})
            imported_count += 1

    # 印出結果摘要
    print(f"✅ 已匯入 {imported_count} 筆資料")

    if errors:
        print(f"\n⚠️  略過 {len(errors)} 筆有問題的資料：")
        for err in errors:
            print(f"   - {err}")

    print("\n=== 匯入完成 ===")


if __name__ == "__main__":
    main()
