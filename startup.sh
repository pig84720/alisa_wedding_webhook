#!/bin/bash
# startup.sh — 啟動 FastAPI 婚禮小幫手後端
# 使用 gunicorn + uvicorn worker。
# Azure App Service 若規格較小，預設 2 個 worker 較能降低記憶體與 outbound 連線壓力。

WEB_CONCURRENCY="${WEB_CONCURRENCY:-2}"
GUNICORN_TIMEOUT="${GUNICORN_TIMEOUT:-120}"

python -m gunicorn \
  -w "${WEB_CONCURRENCY}" \
  -k uvicorn.workers.UvicornWorker \
  main:app \
  --bind 0.0.0.0:8000 \
  --timeout "${GUNICORN_TIMEOUT}"
