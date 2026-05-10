"""
婚禮桌位圖 Excel → Firestore 上傳腳本（修正版）

Excel 實際結構（header=None 讀入）：
  iloc[0]: ['桌次', '主桌', 1, 2, 3, ...]       ← 欄位標題列，略過
  iloc[1]: ['桌位名稱', '主桌', '雙連教會1', ...] ← 真正的桌位名稱
  iloc[2]: [1, '宗鶴', '邱聖惠', ...]            ← 賓客資料開始

寫入兩個 Collection：
  tables/{table_id}  → 桌次詳情
  guests/{auto_id}   → 每位賓客獨立一筆（供姓名查詢）

使用前：
    pip install pandas openpyxl firebase-admin
    將 serviceAccountKey.json 放在同目錄
"""

import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore

EXCEL_PATH = "婚禮桌位圖_範例.xlsx"
SERVICE_ACCOUNT_KEY = "../serviceAccount.json"


def load_seating_data(path: str) -> tuple[list[dict], list[dict]]:
    df = pd.read_excel(path, header=None)

    # iloc[1, 1:] → 實際桌位名稱（主桌, 雙連教會1, ...）
    # iloc[2:, 1:] → 賓客資料
    table_names = df.iloc[1, 1:]
    guest_rows  = df.iloc[2:, 1:]

    tables, guests = [], []

    for col_offset, table_name in enumerate(table_names):
        table_id       = col_offset          # 0 = 主桌, 1 = 第1桌, ...
        table_name_str = str(table_name).strip()

        col_guests = [
            str(name).strip()
            for name in guest_rows.iloc[:, col_offset]
            if pd.notna(name) and str(name).strip()
        ]

        tables.append({
            "table_id":     table_id,
            "table_name":   table_name_str,
            "guests":       col_guests,
            "total_guests": len(col_guests),
        })

        for name in col_guests:
            guests.append({
                "name":       name,
                "table_id":   table_id,
                "table_name": table_name_str,
            })

    return tables, guests


def upload_to_firestore(tables: list[dict], guests: list[dict]) -> None:
    cred = credentials.Certificate(SERVICE_ACCOUNT_KEY)
    firebase_admin.initialize_app(cred)
    db = firestore.client()

    # --- 清除舊資料後重寫 tables ---
    batch = db.batch()
    for table in tables:
        ref = db.collection("tables").document(str(table["table_id"]))
        batch.set(ref, table)
    batch.commit()
    print(f"✅ tables：寫入 {len(tables)} 桌")

    # --- 清除舊 guests 後重寫（分批，上限 500）---
    # 先刪除所有舊文件
    old_guests = db.collection("guests").stream()
    del_batch  = db.batch()
    count = 0
    for doc in old_guests:
        del_batch.delete(doc.reference)
        count += 1
        if count % 500 == 0:
            del_batch.commit()
            del_batch = db.batch()
    if count % 500 != 0:
        del_batch.commit()
    if count:
        print(f"🗑  guests：刪除 {count} 筆舊資料")

    # 寫入新資料
    BATCH_SIZE = 500
    for i in range(0, len(guests), BATCH_SIZE):
        batch = db.batch()
        for guest in guests[i : i + BATCH_SIZE]:
            ref = db.collection("guests").document()
            batch.set(ref, guest)
        batch.commit()
    print(f"✅ guests：寫入 {len(guests)} 位賓客")


def preview(tables: list[dict], guests: list[dict]) -> None:
    print("\n── tables 預覽 ──")
    for t in tables[:3]:
        print(f"  [{t['table_id']}] {t['table_name']} → {t['guests'][:3]}...")
    print("\n── guests 預覽 ──")
    for g in guests[:5]:
        print(f"  {g['name']} / table_id={g['table_id']} / table_name={g['table_name']}")
    print()


def main():
    print("📖 讀取 Excel...")
    tables, guests = load_seating_data(EXCEL_PATH)
    print(f"   {len(tables)} 桌 / {len(guests)} 位賓客")
    preview(tables, guests)

    print("☁️  上傳至 Firestore...")
    upload_to_firestore(tables, guests)
    print("\n🎉 完成！")


if __name__ == "__main__":
    main()