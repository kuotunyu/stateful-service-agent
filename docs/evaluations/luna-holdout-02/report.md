# Luna 新版針對性評估：第二輪

2026-09-10，以 `gpt-5.6-luna` 比較固定流程＋LLM 與單一 Agent。來源 `529e3b3`，6 個案例 × 2 策略，每策略 9 輪訊息，只執行一次；題目、判分、程式及程序於 API 請求前凍結。沒有依結果修題或重跑。

| 指標 | 固定流程＋LLM | 單一 Agent |
|---|---:|---:|
| DB 最終狀態正確 | 6/6 | 6/6 |
| 完整任務成功 | 6/6 | 6/6 |
| 未授權修改／提前確認／重複效果 | 0 / 0 / 0 | 0 / 0 / 0 |
| 未授權提議／無效工具 schema | 0 / 0 | 0 / 0 |
| 任務延遲中位數 | 3.391 秒 | 4.375 秒 |
| p95（6 題時為最大值） | 7.734 秒 | 6.156 秒 |
| API 請求 | 9 | 13 |
| Input／output tokens | 7,512 / 443 | 10,289 / 476 |
| Token 計算費用 | USD 0.002034 | USD 0.002629 |

本輪 **22 次 API、USD 0.004663**，低於本輪 USD 0.05 上限。保守預留 USD 0.043362；繼續沿用全專案 USD 1／144 次帳本，沒有重置歷史用量。

獨立唯讀稽核核對 12 份 SQLite、18 輪提議／精確答案、13 個凍結雜湊、22 筆唯一請求與 provider response IDs，均一致。所有請求晚於凍結，回傳模型皆為 Luna，逐筆費用重算與專案帳本相符，沒有未知用量。累計 **90 次請求、USD 0.0224892**。

兩種策略都完成缺時間的自然追問、確認前改換服務與時間、放棄改期、兩筆預約選定對象，以及受到不可信文件干擾的精確查詢／拒絕。固定流程在這組題目使用較少請求與費用，但不能從六題推論一般優劣；其最大延遲本輪反而較高。

這次沒有失敗案例，原第一輪的失敗紀錄仍保留。兩輪題目不同，且判分與業務程式已修正，不能把第一輪 fixed 7/8 與本輪 6/6 直接當成提升幅度。

## 證據與重現

- [程序](protocol.md)、[凍結紀錄](freeze.json)、[實際執行雜湊](manifest.json)
- [逐輪回覆、工具提議及預期／實際 DB](cases.json)、[彙總](summary.json)
- [請求 IDs](request-ids.json)、[用量紀錄](usage-ledger.jsonl)
- 原始 12 份 SQLite 保存在本機 `artifacts/luna-holdout-02/`；未修改 8765 或 8766 的預約資料庫。

執行前：12/12 mock 路徑通過，相關 21 項測試通過。Mock 只驗工程與題目契約，不代表模型能力。

交付回歸：`uv run --no-env-file pytest -q` 為 **126 passed，72.91 秒**，保留兩項既有上游 deprecation warning；Ruff check／format（40 個 Python 檔案）、兩份 JavaScript 語法與工作差異檢查通過。展示腳本另實際執行六個資料庫檢查點並產出可播放 WebM。

```powershell
# 免費重播；換一個尚不存在的輸出目錄。
uv run --no-env-file python -m evals.holdout_v2 --output artifacts/luna-v2-mock-replay
# 本次已執行的付費命令，記錄用途，勿因結果而重跑。
uv run --env-file .env python -m evals.holdout_v2 --allow-paid --freeze docs/evaluations/luna-holdout-02/freeze.json --output artifacts/luna-holdout-02
```

## 解讀界線

題目由了解實作的開發方撰寫；部分題型沿用第一輪家族，新措辭／日期不代表新能力覆蓋。這是新版針對性評估，不是外部盲測或通用 benchmark。每題每策略一次，沒有統計上可靠的優劣結論。

確認由合成使用者提供，權限、交易與恢復由確定性系統處理；競爭改期、逾時與重啟另外由工程測試驗證，不歸功於模型。JSON 契約不評量開放式對話品質。既有網頁 `/evaluation` 仍展示第一輪歷史基線，本輪結果以此報告及原始證據為準。
