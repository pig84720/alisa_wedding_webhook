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
        "https://firebasestorage.googleapis.com/v0/b/alisa-wedding.firebasestorage.app/o/messageImage_1777993123911.jpg?alt=media&token=7d470141-f717-4435-b3bb-3db225a73990",
    ],
    "church_images": [
        "https://firebasestorage.googleapis.com/v0/b/alisa-wedding.firebasestorage.app/o/messageImage_1777993364477.jpg?alt=media&token=9664ac3a-f7f7-492c-9023-59c44399b195",
    ],
    "church_map_url": "https://maps.app.goo.gl/oudBfg4z8kNVvS3s8",
    "venue_images": [
        "https://firebasestorage.googleapis.com/v0/b/alisa-wedding.firebasestorage.app/o/S__114745360.jpg?alt=media&token=35802849-a3c8-4820-99f4-c782127e8184",
        "https://firebasestorage.googleapis.com/v0/b/alisa-wedding.firebasestorage.app/o/S__114745361.jpg?alt=media&token=ab2d1ac8-c819-4454-b16d-a8d81e35a498",
    ],
    "venue_map_url": "https://maps.app.goo.gl/49kvaCrkoy8YgcVn6",
}

db.collection("settings").document("main").set(data, merge=True)
print("✅ settings/main 更新完成")