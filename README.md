# Stateful Service Agent

可中斷、可恢復、以資料庫結果驗證的維修預約工作台。
提供繁中對話、預約表單、確認單、目前預約、提交收據與執行紀錄。
查詢、建立、改期、取消皆可操作；所有資料均為本機合成資料。
**預設使用免費的規則 mock；可明確啟用真實模型，再於介面選擇固定流程或單一 Agent。**

## 啟動

已安裝 `uv` 的 Windows 電腦可直接雙擊 **`start.cmd`**，會以 Mock 啟動並開啟工作台。
同一路徑服務已在執行時直接重用；其他服務占用連接埠時拒絕啟動，不會停止它。

```powershell
.\start.cmd --live
uv run --no-env-file python -m agent.launch --status
```

`--live` 才會載入本專案 `.env`，介面仍先選 Mock，不會因啟動而呼叫 API。
背景服務日誌在 `data/launcher-8765.log`；狀態查詢會顯示本服務 PID，若要手動停止，僅停止該 PID。
不同埠也不能同時服務同一份預約資料庫，作業系統鎖會阻止第二個 server 啟動恢復程序。
要展示 Ctrl+C／重啟流程，可改用下方前景啟動命令。

工作台底部可開啟 **「查看模型評估與失敗紀錄」**，或直接前往 <http://127.0.0.1:8765/evaluation>。
這是唯讀的保存結果，可篩選失敗、展開逐輪提議、比對 DB 與下載固定證據檔案，不會消耗 API 額度。

已在 Windows、Python 3.14.5 驗證。在 PowerShell 執行：

```powershell
Set-Location -LiteralPath 'D:\AI-Portfolio\CC_github部隊\stateful-service-agent'
uv sync --locked
uv run python -m uvicorn agent.app:create_app --factory --host 127.0.0.1 --port 8765
```

開啟 <http://127.0.0.1:8765>。資料庫為 `data/bookings.db`，停止程序後保留。
若埠號被占用，換一個埠號，不要停止其他專案。
保留同一瀏覽器 cookie，即可在重啟後繼續原工作階段。
目前採**單一 server process**，不要加 `--workers` 或用熱重載展示恢復。
另一份示範資料可在啟動前設定 `$env:STATEFUL_DB = 'data/demo2.db'`。

已取得本專案 API 預算授權、並在 `.env` 放入 `STATEFUL_OPENAI_API_KEY` 後，改用：

```powershell
uv run --env-file .env python -m uvicorn agent.app:create_live_app --factory --host 127.0.0.1 --port 8765
```

介面仍先選 Mock；在「對話方式」選真實模型才會發送付費請求。兩個策略使用同一
`gpt-5.6-luna` 設定（reasoning_effort=none、temperature=0、最多 500 output tokens）；模型只能提出草案，所有寫入仍由確認單授權。
等待模型時可按「停止這次處理」，再送新需求。已送出的 API 呼叫無法保證免計費，
但遲到回覆會失效，尚未送出的後續步驟會停止。

`data/model-usage/allowance.db` 保存網頁共用用量，首次建立時納入首輪 pilot 的
33 次請求及 USD 0.0897152 保守預留；總上限保持 **USD 1／144 次**。
網頁顯示已知 token 費用、保守預留、未知用量筆數；每次先以短交易預留，
網路逾時或重啟不退回預留，也不自動重送。**保留此目錄，刪除它會遺失後續用量紀錄。**
評估 CLI 與網頁現在共用此帳本；每輪另保存本輪用量，不會因換輸出目錄重置總預算。

真實介面整合已驗證建立、改期、取消及查詢，新增 5 次 API、USD 0.0016772；
截至該次驗證累計 38 次、USD 0.0117524。見 [整合驗證紀錄](docs/evaluations/live-smoke-01/report.md)。

目前預設模型已依使用者要求改為 **GPT-5.6 Luna**。Luna 遷移另用 6 次 API、USD 0.0013088，
包含一筆被正確攔下的時間格式錯誤及修正後四個成功流程；累計 44 次、USD 0.0130612。
見 [Luna 遷移驗證](docs/evaluations/luna-migration-01/report.md)。歷史 4.1-mini 評估保留，不能算成 Luna 的能力證據。
目前任務狀態與未完成項目見 [專案進度](docs/status.md)。

新題組已完成凍結後單次實測：兩策略 DB 各 8/8；完整任務 fixed 7/8、agent 8/8，
沒有越權修改或重複效果。唯一失敗是拒絕答案未遵守 JSON 格式。本輪 24 次 API、USD 0.004765。
見 [Luna 新題組報告](docs/evaluations/luna-holdout-01/report.md)；樣本小，不能宣稱策略一般優劣。

## 五分鐘展示

1. 輸入「預約冷氣維修，明天 10:00」。確認前預約列表不變；按確認後看收據與版本。
2. 預約卡按「改期」，輸入「後天 14:00」，確認後檢查時間與版本。取消預約同樣需要確認。
3. 提出另一筆預約，接著傳送「先不要」；舊確認失效，沒有新增預約。
4. 展開「可靠性示範」，選「已提交，但回覆遺失」。确认後按「查證結果與恢復」；仍只有一筆效果。
5. 選「提交前逾時」，確認後在**本工作台終端**按 Ctrl+C，再以相同命令啟動並重新整理原頁面。仍有效的原操作會恢復一次。
6. 再試提交前逾時，但先送「先不要」再恢復；這次不應新增預約。
7. 啟用真實模型後選「固定流程」，正常預約或改期；等待時按「停止這次處理」，確認舊回覆沒有新增待確認操作。

確認期限 5 分鐘。超過期限只取消未提交工作，不自動重新授權。
「放棄這次操作」只取消尚未提交的工作；已提交預約需另行確認取消，不承諾任意撤銷。

## 架構與邊界

```text
瀏覽器對話／表單 → 伺服器 session、CSRF、輸入驗證
  → mock 或模型的操作提議 → 等待使用者明確確認
  → 業務規則、擁有者、意圖版本、預約版本與期限檢查
  → SQLite 短交易：預約變更 + 已提交狀態 + 收據
  → 同一讀取快照中的目前預約與操作結果
```

- `agent/service.py` 為業務／授權邊界；`agent/db.py` 保存 sessions、messages、operations、bookings、events。
- 狀態：`draft`、`waiting_confirmation`、`executing`、`committed`、`failed`、`cancelled`。
  逾時另外標示 `delivery=unknown`，不能當作業務失敗重做。
- 新訊息先持久化意圖版本，再在交易外解析。延遲提議和提交都必須通過版本檢查。
- 確認 token 綁定不可變操作；重複請求 ID 綁定相同內容；確認重試回傳原收據。
- 有效時段唯一限制模擬一位技師；預約版本防止競爭改期覆寫。
- 模型看不到確認 token，不能填身分或使用確認工具。工具文字、文件和模型輸出皆為不可信資料。
- 伺服器示範身分固定為 `demo-alice`，cookie 辨識工作階段。這**不是正式登入系統**；不同瀏覽器會看到同一示範使用者的預約。
- 故障展示在本機工具邊界注入回覆遺失；沒有宣稱支援任意外部 SaaS 的 exactly-once 語意。

## 驗證與比較

```powershell
uv run pytest -q
uv run ruff check agent evals tests
uv run ruff format --check agent evals tests
node --check agent/static/app.js
uv run python -m evals.run --output artifacts/my-mock-run
```

若尚未安裝 Playwright Chromium，先執行 `uv run playwright install chromium`；
或只跑 `uv run pytest -q --ignore=tests/test_browser.py`。
瀏覽器測試自行啟停自己的 server，使用獨立資料庫，截圖輸出到 `artifacts/`。
恢復測試實際終止子程序，沒有只靠 mock 宣稱重啟成功。

評估限維修預約：12 案例 × 2 策略，各使用獨立資料庫。
`fixed` 固定查詢 context，再呼叫模型解析；`agent` 由單一模型選工具，每輪最多 6 步。
共用 `agent/orchestration.py` 的工具、政策、模型設定及 `BookingService`。
確認來自獨立合成使用者事件，模型不能替自己授權。

`cases.json` 保存逐案預期／實際 DB、回覆、工具提議和失敗；`summary.json` 保存
最終狀態正確率、未授權修改、重複效果、任務成功率、延遲、token 及費用。
資料库逐欄比對擁有者、服務、時間、狀態與版本；任務成功另要求對應流程條件，不使用 LLM judge。
查詢／拒絕文字的檢查是有限的固定事實或詞彙檢查，不能完整評估回答品質。
小樣本 p95 使用 nearest-rank，因此 12 案的 p95 是最大值；延遲包含本機業務處理，排除初始化。

**Mock 結果不是模型能力或策略優劣的證據。** 第一輪真實模型 pilot 已完成：
兩策略各 12 案符合預期 DB 狀態，未授權修改與重複操作為 0；33 次 API 請求，token 計算費用 USD 0.0100752。
完整 [真實模型比較報告](docs/evaluations/paid-pilot-01/report.md) 保存結果、版本、用量與限制。
這是開發案例，只有六種不同初始提示；不能當作未見題組上的一般能力證明。

## 真實模型 pilot：已完成首輪

Luna 新題組先執行 mock，凍結 hash，再開啟付費。規則與限制見 [新題組程序](docs/evaluations/holdout-protocol.md)。
以下命令皆使用新輸出路徑：

```powershell
uv run python -m evals.holdout --output artifacts/holdout-mock-new
uv run python -m evals.holdout --freeze artifacts/holdout-new.freeze.json
uv run --env-file .env python -m evals.holdout --output artifacts/holdout-paid-new --freeze artifacts/holdout-new.freeze.json --allow-paid
```

凍結題組重跑不再算未見題測試；看過失敗後調整提示，也應另立新題組。Mock 結果不算模型成績。

候選 `gpt-4.1-mini-2025-04-14`、temperature 0、每次最多 500 output tokens；
12 案 × 2 策略，總共最多 **144 次請求、USD 1**。達上限即停止請求。
此快照是固定版本、低成本的初始基線，不宣稱是最新或最佳模型。
官方標準價格：每百萬 input tokens USD 0.40、output tokens USD 1.60。
[官方模型與價格](https://developers.openai.com/api/docs/models/gpt-4.1-mini)。

首輪已取得 USD 1 授權並完成，沒有超出上限。後續重跑會另外產生費用，需計入既有授權總額。
以下指令是首輪當時版本的紀錄；目前評估程式預設也已改為 Luna，不能用新版本指令重現舊模型設定。
本專案支援使用者指定的 `.env`；金鑰欄位為 `STATEFUL_OPENAI_API_KEY`，範例見 `.env.example`。
只有明確執行付費命令才會載入 `.env`；預設網頁不會讀取金鑰。首輪啟動方式如下；
該目錄與 ledger 現已存在，重複執行會被拒絕，不會重置首輪預算：

```powershell
uv run --env-file .env python -m evals.run --output artifacts/paid-pilot-01 --allow-paid --budget-usd 1
```

不要把金鑰貼進對話或讀取其他專案 `.env`。預設 UI 不讀取此金鑰。
Adapter 只呼叫固定官方 endpoint，無自動重試。請求前以保守 token 上界預留費用並持久化 ledger；
逾時保留預留額。既有輸出目錄不可重用；全專案共用持久預算，重啟與新一輪評估不會重置額度。
價格須在真正執行前再核對；應用程式估算不含稅或帳戶級額外收費。
真實端點已由首輪 33 次成功請求驗證。自動測試仍使用隔離的 HTTP 回覆，執行 `pytest` 不會產生 API 費用。

## 失敗案例

| 觸發 | 預期結果 |
|---|---|
| 舊確認／延遲回覆／新意圖 | 拒絕舊版本，無過期提交 |
| 他人預約／模型偽造身分 | 拒絕，保護資料不變 |
| 重複請求／確認 | 重用原請求或收據 |
| 競爭改期／搶時段 | 一筆成功，另一筆明確失敗 |
| 提交前／後逾時 | 查收據，僅恢復仍有效的原操作 |
| 解析途中重啟 | 訊息標示中斷，不自動確認草案 |
| 網路失敗後重試／反悔 | 重試沿用 ID；不同訊息為新意圖 |
| 預算不足／模型回覆不完整 | 停止或記錄失敗，不假稱成功 |

決策摘要見 [實作計畫](docs/implementation.md)。
預定 GitHub：`kuotunyu/stateful-service-agent`。目前僅本機開發，沒有 remote、push 或部署。
