# 原生 200% 縮放追加驗收

2026-09-10，Windows Edge **152.0.4191.66**，1280×900 實體視窗，以臨時擴充功能呼叫 `chrome.tabs.setZoom(tabId, 2)`。沒有修改 CSS zoom 或用縮小 viewport 假冒原生縮放。

瀏覽器 `getZoom` 回報 **2**，`devicePixelRatio=2`、`innerWidth=640`、`scrollWidth=640`，CSS zoom 仍為 **1**。首頁、改期預覽與評估失敗詳情三個階段均無整頁水平溢出。

實際以免費 Mock 完成：提出洗衣機維修 → 下一步焦點到確認標題 → 明確確認 → 改期選日期／時段 → 預覽 → 明確確認。預覽前 DB 無新增；改期預覽仍為版本 1；確認後只有一筆 `2030-05-02 16:00 +08:00`、版本 2。另驗證評估失敗入口能以 Enter 開啟並篩出一筆案例。

- [原始量測及最終 DB 查詢](result.json)
- [首頁](01-home.png)、[改期確認](02-reschedule-preview.png)、[評估詳情](03-evaluation.png)

重跑：

```powershell
uv run --no-env-file python scripts/verify_native_zoom.py --output artifacts/native-zoom-new
```

需本機 Edge、專案 dev dependencies 與 Playwright。使用臨時瀏覽器 profile、臨時擴充功能及測試 server；只關閉自己的測試程序，不修改現有瀏覽器設定、8765／8766、預約或 API 帳本。輸出目錄必須尚未存在。

曾發現 Playwright 在原生 zoom 下以 CSS 座標裁切截圖，造成全頁裁切／空白，已改用 CDP compositor 的 viewport 截圖並目視核對。此為截圖工具差異，沒有為此改動產品版面。

此項補足原先僅 CSS zoom 的驗證。**實際 NVDA／同級讀屏仍未驗證**：未找到標準 NVDA 安裝位置或執行中程序；沒有以 DOM 或本次瀏覽器測試冒充讀屏測試。結果限於這個 Edge 版本及已測流程，不代表完整 WCAG 認證或所有瀏覽器皆已驗證。
