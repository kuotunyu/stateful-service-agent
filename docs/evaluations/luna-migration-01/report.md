# GPT-5.6 Luna 遷移驗證

2026-09-10，使用者指定改用 `gpt-5.6-luna`。保留 Chat Completions JSON 決策格式、temperature 0、
500 output token 上限，明確指定 reasoning_effort=none，避免新模型預設 medium 改變原本非推理流程。
業務工具、確認與 SQLite 交易邊界沒有放寬。UI 與未來評估預設一起切換；舊報告與旧價格測試保留。

依 [官方模型頁](https://developers.openai.com/api/docs/models/gpt-5.6-luna)、
[官方標準價格](https://developers.openai.com/api/docs/pricing) 及
[遷移指引](https://developers.openai.com/api/docs/guides/upgrading-to-gpt-5p6-sol)，
每百萬 ordinary input／cache read／cache write／output 為 USD 0.20／0.02／0.25／1.20。
預留按最高輸入單價计算，超過 272K 保守輸入上界直接拒絕，不進入長上下文計價。
新帳本同時記錄請求模型、回傳模型與 service tier；既有已用額度不重置。

第一個實際請求失敗：Luna 把 `slot` 填成 `10:00`，雖有另填正確 date/time，仍不符合完整 ISO 時間契約。
後端拒絕提議，沒有新增預約。根因是 slot schema 沒有說明格式；只補明確欄位說明，沒有修改驗證規則。
失敗紀錄見 [first-failure.json](first-failure.json)，修正後重新建立獨立資料庫驗證，見 [result.json](result.json)。

修正後四個流程通過：fixed 建立明天 10:00、改期後天 14:00、取消；agent 查詢包含已取消預約。
DB 逐步確認只有一筆預約、版本 1 → 2 → 3、狀態 active → cancelled。
本次共 6 次 API（失敗 1 次、修正後 5 次），token 計算費用 USD 0.0013088；
含歷史累計 44／144 次、USD 0.0130612，保守預留 USD 0.1149479／1，無未知用量。

這是以失敗修正提示後的開發整合驗證，**不是獨立能力比較，也不能推論 Luna 的一般成功率**。
尚未以未見題組比較 Luna 的 fixed／agent；舊 4.1-mini 的 12×2 結果不能搬到 Luna 名下。
