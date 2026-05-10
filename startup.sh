#!/bin/bash
# startup.sh — 啟動 FastAPI 婚禮小幫手後端
# 使用 gunicorn + uvicorn worker，4 個 worker process

python -m gunicorn -w 4 -k uvicorn.workers.UvicornWorker main:app --bind 0.0.0.0:8000
