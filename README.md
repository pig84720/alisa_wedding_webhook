# our_wedding_20261004_webhook

## Internal Load Test

先在 Azure App Service 設定 `DIAGNOSTIC_TOKEN`，再使用受保護的壓測探針：

```bash
curl -H "X-Diagnostic-Token: <token>" \
  "https://your-app.azurewebsites.net/internal/diagnostics/load-probe?scenario=seat_lookup&query_name=王小明"
```

若要做併發壓測，可直接使用：

```bash
python tools/load_test_internal.py \
  --base-url https://your-app.azurewebsites.net \
  --token <token> \
  --scenario seat_lookup \
  --concurrency 100 \
  --requests 300
```

`settings_read` 較輕量，適合先確認平台本身；`seat_lookup` 會掃描座位資料並計算模糊比對，較接近婚禮當天實際查桌號的壓力。

Seat lookup 現在會使用每個 gunicorn worker 的記憶體快取。若你剛更新 Firestore 座位資料，想立刻刷新快取，可額外帶上：

```bash
curl -H "X-Diagnostic-Token: <token>" \
  "https://your-app.azurewebsites.net/internal/diagnostics/load-probe?scenario=seat_lookup&query_name=王小明&refresh_cache=true"
```
