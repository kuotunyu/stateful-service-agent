# Stateful Service Agent

可中斷、可恢復，以 SQLite 最終狀態驗證結果的模擬維修預約工作台。
可查詢、建立、改期與取消；模型只能提議，資料庫寫入需要使用者確認。
所有資料皆為本機合成資料，不連接真實客戶、付款、通知或行事曆。

## 啟動

Windows 已安裝 `uv` 後，在專案目錄執行，或雙擊 `start.cmd`：

```powershell
.\start.cmd
# 啟用 GPT-5.6 Luna，需要本專案 .env 與 API 預算授權
.\start.cmd --live
# 查看服務狀態與 PID
uv run --no-env-file python -m agent.launch --status
```

工作台：<http://127.0.0.1:8765/>；保存的模型比較：<http://127.0.0.1:8765/evaluation>。
預設為免費規則 Mock。`--live` 載入本專案 `.env` 的 `STATEFUL_OPENAI_API_KEY`，
仍須在介面選擇固定流程或單一 Agent 才會呼叫模型。啟動與評估結果頁不產生 API 費用。

啟動器只重用相同專案、資料庫與相容模式的服務；占用埠時拒絕啟動，不會停止其他程序。
日誌在 `data/launcher-8765.log`；`$env:STATEFUL_DB = 'data/demo2.db'` 可指定另一份資料庫。
不同資料庫的瀏覽器工作階段分開，同一資料庫只允許一個 server process。

需要前景終端展示停止／重啟時：

```powershell
uv sync --locked
uv run --no-env-file python -m uvicorn agent.app:create_app --factory --host 127.0.0.1 --port 8765
# 真實模型前景模式
uv run --env-file .env python -m uvicorn agent.app:create_live_app --factory --host 127.0.0.1 --port 8765
```

已在 Windows、Python 3.14.5 驗證。資料庫預設 `data/bookings.db`；保留資料庫與 cookie 即可繼續。
不要加 `--workers` 或用熱重載展示恢復。

## 五分鐘展示

1. 輸入「預約冷氣維修，明天 10:00」。確認前 DB 不變；確認後看預約、版本與收據。
2. 預約卡按「改期」，直接選新日期與時段，按「預覽改期」。核對原預約編號、原時間與新時間後確認；取消亦需確認。
3. 提出另一筆預約，再傳送「先不要」；舊確認失效，不新增預約。
4. 展開「可靠性示範」，選「已提交，但回覆遺失」。確認後查證，仍只有一次效果。
5. 選「提交前逾時」，確認後停止本專案前景終端，再用相同命令啟動；有效的已確認操作恢復一次。
6. 真實模式等待時按「停止這次處理」，再提出新需求；遲到提議不得成為待確認操作。

確認期限五分鐘。未提交操作可放棄；已提交預約須另行提出並確認取消，不承諾任意撤銷。
已發送的模型請求可能仍計費。模型文字標示未經查證；是否提交以 DB 查證與收據為準。

「查看目前預約」與「重新查詢」保留待確認草案；在對話中送出新訊息則會取代舊意圖。
免費 Mock 支援今天、明天、後天或明確日期，以及 10:00／14:00／16:00；不熟悉語法可直接用表單。
錯誤時間可以接著修正，但舊確認不會復活。取消後的預約仍保存在「已取消紀錄」。

## 架構與邊界

```text
對話／表單 → server session + CSRF → Mock／固定流程＋LLM／單一 Agent
  → 提議：身分、意圖版本、模型觀測的預約版本、時間規則
  → 使用者確認：再檢查版本、期限與操作對象
  → SQLite 短交易：預約變更 + 已提交狀態 + 收據 → 查證與恢復原操作
```

- 模型呼叫在交易外；`agent/service.py` 是業務與授權邊界，模型不能提供身分或使用確認工具。
- 狀態為草案、等待確認、執行中、已提交、失敗、取消；回覆遺失另外標記結果未知。
- 同一請求 ID 重用結果，同一確認重用收據；唯一時段與預約版本防止重複效果、競爭覆寫。
- 對話保存於 DB；模型收到最近八輪、每則至多 2,000 字的文字上下文，不包含確認 token 或工具物件。
- 新訊息使未提交操作失效；模型讀過的預約若已變更須重新查詢，矛盾時間欄位直接拒絕。
- 文件、工具文字及歷史對話皆為不可信資料；歷史文字不能授權或取代目前 DB 狀態。
- 示範身分固定為 `demo-alice`，不是正式登入；不同瀏覽器仍代表同一合成使用者。
- 故障注入限本機交易邊界，沒有宣稱任意外部 SaaS 的 exactly-once 保證。

## 驗證與模型比較

```powershell
uv run --no-env-file playwright install chromium
uv run --no-env-file pytest -q
uv run --no-env-file ruff check agent evals tests
uv run --no-env-file ruff format --check agent evals tests
node --check agent/static/app.js
node --check agent/static/evaluation.js
uv run --no-env-file python -m evals.holdout --output artifacts/holdout-mock-new
```

測試使用隔離資料庫與假模型，不產生 API 費用。瀏覽器測試僅啟停自己的測試 server。
Mock 通過是工程證據，不是模型能力證據。

最新 [Luna 新版針對性評估](docs/evaluations/luna-holdout-02/report.md)：6 題 × 2 策略，兩者 DB 與任務皆 6/6；22 次 API、USD 0.004663。題型與第一輪部分重疊，不能據此推論一般能力或改善幅度。

第一輪保存基線為 [Luna 凍結新題組](docs/evaluations/luna-holdout-01/report.md)：
固定流程 DB 8/8、任務 7/8；單一 Agent DB 8/8、任務 8/8；24 次 API、USD 0.004765。
唯一任務失敗為拒絕答案未遵守 JSON 格式。樣本小，不能據此宣稱策略一般優劣。

**第一輪成績屬於先前凍結來源，不能當作新版實測；新版結果請見第二輪報告。**
新版評分增加確認前 DB／授權邊界檢查與 schema 拒絕統計；既有報告保持原樣。
兩策略共用工具、政策與 Luna 設定；固定流程先提供 context，單一 Agent 自行選工具，每輪最多六步。
判分比對預期／實際 DB，不使用 LLM judge；自由文字品質與廣泛泛化能力仍需獨立評估。

模型設定：`gpt-5.6-luna`、`reasoning_effort=none`、temperature 0、最多 500 output tokens。
網頁與評估共用 `data/model-usage/allowance.db`，硬上限 USD 1／144 次；未知用量保留預留額、不自動重送。
保留整個用量目錄，刪除會遺失後續帳本。價格與估算界線見 [Luna 遷移紀錄](docs/evaluations/luna-migration-01/report.md)。

## 交付與限制

- [目前進度](docs/status.md)、[審查修正](docs/review-fixes.md)、[新題組程序](docs/evaluations/holdout-protocol.md)。
- [首次使用流程改善與驗收](docs/ux-review/2026-09-10/施工驗收紀錄.md)：操作入口、改期、錯誤接續、確認到期、評估閱讀與剩餘驗證限制。
- [操作展示錄影與資料庫檢查點](docs/demo/README.md)。
- [逾時不等於失敗：Manim 中文解說動畫](docs/demo/timeout-explainer/README.md)，約 52 秒，附文字稿、原始碼及既有證據來源。
- 歷史：[初版實作](docs/implementation.md)、[4.1-mini 初測](docs/evaluations/paid-pilot-01/report.md)、[介面整合](docs/evaluations/live-smoke-01/report.md)。
- 原始碼：[kuotunyu/stateful-service-agent](https://github.com/kuotunyu/stateful-service-agent)。工作台沒有對外部署。

本次範圍不含正式登入、多人正式服務、外部通知、GPU、多 Agent 平台或通用 benchmark framework。
