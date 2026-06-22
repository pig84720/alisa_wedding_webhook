"""
更新 Firestore settings/main 文件
執行前：pip install firebase-admin
將 serviceAccountKey.json 放在同目錄
"""

import firebase_admin
from firebase_admin import credentials, firestore

cred = credentials.Certificate("../serviceAccount.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

data = {
    "ceremony_images": [
        "https://firebasestorage.googleapis.com/v0/b/alisa-wedding.firebasestorage.app/o/%E5%84%80%E7%AF%80%E8%A1%A8%E6%9B%B4%E6%96%B0P1.jpg?alt=media&token=eeb38748-6eb4-49cb-aa94-d4dba18f14fb",
        "https://firebasestorage.googleapis.com/v0/b/alisa-wedding.firebasestorage.app/o/%E5%84%80%E7%AF%80%E8%A1%A8%E6%9B%B4%E6%96%B0P2.jpg?alt=media&token=f5d70b2b-bee8-48f0-a58b-0140bde9b844",
    ],
    "church_images": [
        "https://firebasestorage.googleapis.com/v0/b/alisa-wedding.firebasestorage.app/o/messageImage_1777993364477.jpg?alt=media&token=9664ac3a-f7f7-492c-9023-59c44399b195",
    ],
    "church_map_url": "https://maps.app.goo.gl/oudBfg4z8kNVvS3s8",
    "venue_images": [
        "https://firebasestorage.googleapis.com/v0/b/alisa-wedding.firebasestorage.app/o/1779629958304.jpg?alt=media&token=f4bc3284-6b23-4f0c-81dc-7f327b5ad888",
        "https://firebasestorage.googleapis.com/v0/b/alisa-wedding.firebasestorage.app/o/1779629802779.jpg?alt=media&token=6613d653-49f6-463c-a3c1-a7f386b24c6e",
    ],
    "venue_map_url": "https://maps.app.goo.gl/49kvaCrkoy8YgcVn6",
}

db.collection("settings").document("main").set(data, merge=True)
print("✅ settings/main 更新完成")