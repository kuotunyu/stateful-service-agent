# Repair Desk 首次使用流程改善 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 若執行環境沒有此技能，依本文件逐項施工與驗收即可；不要因技能名稱缺失而重建整個網站。

**Goal:** 讓第一次使用者能開始預約、直接選日期改期、在錯誤後繼續、清楚找到確認與結果，同時保留所有明確確認和資料可靠性邊界。

**Architecture:** 保留 FastAPI、SQLite、原生 HTML/CSS/JavaScript。優先改善現有頁面與確定性 Mock 錯誤恢復；不新增前端框架，不改寫整套代理架構。真正影響意圖與確認的變更由 `BookingService` 把關，前端不自行宣布寫入成功。

**Tech Stack:** Python ≥3.10、FastAPI、SQLite、原生 DOM、pytest、Playwright、ruff、uv。

## 執行前必讀

執行註記：使用者後續已批准本計畫。實際施工基準為包含可靠性修正的 `ed1dd5c`，逐項結果與剩餘限制見 [施工驗收紀錄](../../ux-review/2026-09-10/施工驗收紀錄.md)。以下保留原始規劃及檢查項目，不將歷史基準改寫為新版成果。

本計畫依 2026-09-10 的版本 `540bc64` 和 computer use 實測撰寫；尚未執行。先讀 [使用體驗報告](../../ux-review/2026-09-10/使用體驗報告.md)，查看 J01–J20 路徑、U01–U11 問題和截圖。以下是建議採用的產品決策，使用者尚未逐條審核；未來收到不同產品方向時，以新指示為準。

### 全域約束

- 維持繁體中文、Repair Desk 品牌、藍白介面、黃色確認單；此次是改善流程，不是品牌重做。
- 保持冷氣／洗衣機、Asia/Taipei、10:00／14:00／16:00、未來時段。
- 建立、改期、取消都必須明確確認。任何補資料、重試、恢復填寫、查詢及頁面跳轉都不能代替確認。
- 舊 intent revision、舊 confirmation token、過期操作不得恢復為可提交。已提交結果仍以 DB 收據為準。
- `executing`／結果未知不能自動重做；提交前反悔、中斷、延遲結果失效、同 request ID 重試不得退化。
- 首輪驗收全部免費 Mock 或 stub model。勿載入 `.env`、改寫用量帳本或啟動付費評估。
- 不刪現有資料庫、歷史評估、失敗證據或測試；新測試用臨時資料庫。勿重啟使用者正在用的 8765 服務來做自動化測試。
- 既有原始碼檔案不做無關拆分。每個任務一個可獨立驗收的變更；先讀 `git status`，保留使用者未提交修改。
- 不因零筆有效預約刪掉已取消歷史，只改呈現分組。
- 文字、色彩、觸控尺寸是本計畫的設計目標；目前沒有宣稱已通過正式無障礙或效能測試。

## 方向選擇

| 方案 | 好處 | 代價 | 決定 |
|---|---|---|---|
| 只調字級及間距 | 快、風險低 | 無法修復改期、查詢、錯誤接續 | 不足以作為本輪完成定義 |
| 保留雙入口，修正流程與狀態提示 | 可逐項交付，保留作品可靠性特色 | 少量前後端協作 | **採用** |
| 全面改成向導或自由聊天 Agent | 體驗模式統一 | 範圍大、可能需要付費模型，重驗成本高 | 不列入本輪 |

預約與表單共用同一確認單；首頁以「完成模擬預約」為主，技術細節展開後仍可查看。評估頁服務想理解可靠性證據的讀者。

## 檔案地圖

| 檔案 | 責任／修改重點 |
|---|---|
| `agent/static/index.html` | 首屏、完整範例、技術細節折疊、改期表單、欄位錯誤、下一步入口 |
| `agent/static/style.css` | 操作優先版面、手機滾動、字級、焦點與觸控尺寸 |
| `agent/static/app.js` | `renderModel`、`renderMessages`、`renderConfirmation`、`renderBookings`、`renderEvents`、`sendPending`、表單事件 |
| `agent/mock.py` | `parse` 的有限語法說明；`describe` 的缺欄位／確認文案 |
| `agent/service.py` | 結構化時段驗證錯誤；必要時建立新的不完整草案；保留授權核心 |
| `agent/app.py` | Mock 訊息錯誤恢復回應；表單錯誤欄位資料；保留路由與 CSRF |
| `agent/static/evaluation.html`、`evaluation.js`、`evaluation.css` | 直達失敗、一般語言摘要、篩選／展開保存、證據呈現 |
| `tests/test_browser.py` | 利用既有 `live_server`、`send`、`db_bookings` 實作新行為測試 |
| `tests/test_api.py`、`test_edge_cases.py`、`test_service.py` | 錯誤恢復、舊確認失效、純查詢、時段與權限回歸 |
| 新建 `tests/test_ux_validation.py` | T03 的結構化錯誤與安全補資料測試；避免把 UI 文案當商業邏輯 |
| 新建 `docs/ux-review/2026-09-10/施工驗收紀錄.md` | 實際命令、結果、新截圖、未解問題；不得把本次體驗截圖冒充改善後成果 |

## 相依與優先順序

建議順序：**T02 → T03 → T04 → T01 → T05 → T06 → T07 → T08**。T02 的快捷查詢可獨立先交付；T04 依賴 T03 的錯誤欄位；T07 針對前面完成的界面驗收。若時間只夠一輪，先修 T02、T03、T04 和 T05 的手機到達確認入口。

| 任務 | 優先 | 解決問題 | 完成後可見成果 |
|---|---|---|---|
| T01 | P1/P2 | U04、U05、U06、U10 | 新使用者首屏能起步；清楚是免費示範 |
| T02 | P1 | U02 | 兩個查詢按鈕都不取消草案 |
| T03 | P1 | U01、U06 | 無效時段後可接著補對時間，舊確認仍失效 |
| T04 | P1/P2 | U03、U07 | 卡片直接選日期改期；錯誤就在欄位旁 |
| T05 | P1/P2 | U04、U09 | 手機一步到確認；期限主動更新 |
| T06 | P2 | U08 | 完成訊息靠近動作；有效與取消歷史分開 |
| T07 | P2 | U10 | 鍵盤、窄畫面、觸控及朗讀基本可用 |
| T08 | P3 | U11 | 評估頁可直達失敗、保留研究界線 |

---

## T01：操作優先的首屏與誠實的示範引導

**Files:** 修改 `index.html`、`style.css`、`app.js:renderModel/renderMessages`、`mock.py:describe`；測試 `tests/test_browser.py`。

**Interfaces:** 保留 `#message`、`#send`、`#mode`、`#model-usage`；新增 `<details id="model-details">`，不要刪掉用量節點導致 render 出錯。`#interrupt` 保持在 details 外，處理中立刻看得見。T02 的查詢按鈕使用獨立 ID，不再是 `data-prompt`。

- [ ] 空狀態先顯示：「安排一筆模擬維修預約」「選擇項目與時間，確認後才會保存。本示範不會聯絡維修人員。」
- [ ] Mock 選項對外名稱改為「免費示範（固定句型）」；現有 value `mock` 保留。提示：「支援今天、明天、後天或 YYYY-MM-DD；時段為 10:00、14:00、16:00。也可以用表單選日期。」
- [ ] 範例按鈕完整顯示「冷氣維修・明天 10:00」，且可及名稱包含相同日期時段；不得默默把原預約卡「改期」也固定到明天。
- [ ] 模型名稱與統計移到 `model-details`；Mock 摘要標「目前操作不呼叫付費模型」。真實模型選項仍保留明確收費提示，不自動切換。
- [ ] 縮減 intro 上下留白和空對話 minimum height；390×844 與 1280×720 的全新 session，至少一個完整範例或開啟表單 CTA 必須在首屏完整可見。不要以全域縮小文字達成。
- [ ] 空確認單降低黃色面積與視覺權重；有待確認操作後才使用完整黃色卡片。
- [ ] `mock.describe()` 改「已整理好操作內容。請查看確認單；確認後才會修改預約。」缺資料文案改「請補上日期與時段，例如：明天 14:00。目前尚未修改預約。」去掉巢狀引號。

標記示例（放入現有對話區；保留原 ID 對應）：

```html
<details id="model-details">
  <summary>對話模式與用量</summary>
  <label for="mode">對話方式</label>
  <select id="mode">
    <option value="mock">免費示範（固定句型）</option>
    <option value="fixed" disabled>真實模型・固定流程（可能計費）</option>
    <option value="agent" disabled>真實模型・單一 Agent（可能計費）</option>
  </select>
  <p id="model-usage">正在讀取用量…</p>
</details>
<p id="mode-help">免費示範使用固定句型，不呼叫付費模型。</p>
<button type="button" data-prompt="我要預約冷氣維修，明天 10:00">
  冷氣維修・明天 10:00
</button>
```

**驗收範例**：新增到 `test_browser.py`，與既有 fixture 共用；新 test 的 `page` 需在 `sync_playwright()` 內建立。

```python
for size in ({"width": 1280, "height": 720}, {"width": 390, "height": 844}):
    page.set_viewport_size(size)
    page.goto(live_server["url"])
    start = page.get_by_role("button", name="冷氣維修・明天 10:00", exact=True)
    expect(start).to_be_visible()
    box = start.bounding_box()
    assert box and box["y"] >= 0
    assert box["y"] + box["height"] <= size["height"]
    assert not page.locator("#model-details").evaluate("el => el.open")
```

- [ ] 執行 `uv run --no-env-file pytest -q tests/test_browser.py`，再截空首頁桌面／手機。這是幾何與真實畫面驗收，不單測 CSS class 名稱。
- [ ] 審閱 diff，提交單一 T01 變更。

## T02：查詢快捷不取代草案

**Files:** 修改 `index.html`、`app.js`、`app.py:message` 的 query 回覆文案；測試 `tests/test_browser.py`、`tests/test_api.py`。第一輪不更改 `service.py:begin_turn`。

**Interfaces:** 新 `#query-bookings` 與既有 `#refresh` 都呼叫既有 `refresh(): Promise<void>`；不經 `/api/messages`，不新增 message、operation 或 revision。可用既有 `notice()` 顯示有效預約數。

- [ ] 移除查詢快捷的 `data-prompt`，加入 `id="query-bookings"`；標籤可用「查看目前預約」。
- [ ] 統一兩按鈕的讀取流程：`await refresh()` 後顯示「目前有 N 筆有效預約」；如有待確認操作，加「待確認內容已保留」。
- [ ] UI 跳到預約區使用明確連結／focus；不能把 GET 包裝成重新送出聊天。
- [ ] 保留聊天自由文字「查詢」目前會開新意圖的規則，但在該回覆有取消原草案時明講「先前待確認內容已被這則新訊息取代」；輸入說明補上「只想查看安排，可按『查看目前預約』保留草案」。本任務不宣稱自然語言查詢也已保留草案。
- [ ] 若將來要讓自由文字 query 也不改意圖，另開語義變更，需一起設計 mock/live、訊息 revision、延遲回覆及並行行為；不得以 parse 完才取消舊操作的方式弱化新意圖立即失效保障。

核心事件示例：

```javascript
async function queryBookings() {
  try {
    await refresh();
    const count = state.bookings.filter(b => b.status === "active").length;
    notice(`目前有 ${count} 筆有效預約。` +
      (currentOp() ? "待確認內容已保留。" : ""));
  } catch (error) {
    notice(error.message, true);
  }
}
$("query-bookings").addEventListener("click", queryBookings);
// 以相同 handler 取代既有 #refresh 的 listener；不要重複綁定。
```

**完整測試範例**（加入 `tests/test_browser.py`）：

```python
def test_query_controls_preserve_pending_confirmation(live_server):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(live_server["url"])
        send(page, "預約冷氣維修，明天 10:00")
        expect(page.get_by_role("button", name="確認建立預約", exact=True)).to_be_visible()
        original = page.locator("#confirmation").inner_text()
        for selector in ("#query-bookings", "#refresh"):
            page.locator(selector).click()
            expect(page.locator("#confirmation")).to_have_text(original)
            assert db_bookings(live_server) == []
        page.get_by_role("button", name="確認建立預約", exact=True).click()
        expect(page.locator("#booking-count")).to_have_text("1")
        assert len(db_bookings(live_server)) == 1
        browser.close()
```

T05 加入倒數後，不能整塊比字串；改比較操作 ID、項目、日期及按鈕狀態，倒數允許變動。

- [ ] 改前跑此測試確認 query 快捷缺失／草案流失會被測到；實作後通過。執行既有 `test_api.py`、`test_service.py`，保留新文字意圖阻止舊確認的測試。
- [ ] 審閱 diff、提交 T02。

## T03：無效時段後保留「可補齊的新草案」

**Files:** 修改 `service.py`、`app.py`、`mock.py`；新增 `tests/test_ux_validation.py`，補 `test_edge_cases.py`。先處理本次確定性 Mock 與表單；live model 錯誤恢復不是本輪擴充目標。

**安全策略:** 新訊息仍立即讓舊操作失效。驗證錯誤若可修正，建立「目前 revision 的新 draft」，移除無效時間資訊、沒有可確認按鈕；下一輪可從這份新 draft 補日期時段。**不是保留舊 waiting_confirmation，也不是偷偷改舊 payload。**

**Interfaces:**

```python
class SlotValidationError(ValueError):
    def __init__(self, code: str, field: str, message: str):
        super().__init__(message)
        self.code = code
        self.field = field
```

`code` 只使用 `unsupported_time`、`past_slot`、`invalid_slot`；`field` 使用 `time`、`date`、`slot`。`_slot()` 和 `propose()` 現有日期／時段檢查改拋此錯誤，其他 Forbidden／Conflict／未知格式錯誤仍沿用拒絕。

API 回應增加可選欄位，不移除既有 `text/rejected/operation`：

```json
{
  "rejected": true,
  "text": "15:00 不在開放時段。已保留這次改期對象，請選 10:00、14:00 或 16:00。",
  "validation": {"code": "unsupported_time", "field": "time"}
}
```

`operation` 如存在，必須為新產生的 `draft`；內容由既有 service 序列化，不手填 token。前端 T04 用 `validation.field` 定位錯誤，不解析中文句子。

- [ ] `_slot()` 的不開放時段拋 `unsupported_time/time`，過去時段拋 `past_slot/date`；解析失敗拋 `invalid_slot/slot`。`propose()` 的獨立 `time` 驗證同樣分類。
- [ ] `app.py:message()` 在拿到合法 schema 的 proposal 並捕捉 SlotValidationError 時，採下表清除欄位，再 `service.propose(session, turn['revision'], sanitized)`；成功時回新草案與錯誤說明。

| 錯誤 | 新 draft 保留 | 清除 |
|---|---|---|
| unsupported_time | action、已驗證的 booking_id、service、合法且未過去的 date | slot、time |
| past_slot | action、已驗證的 booking_id、service | slot、date、time |
| invalid_slot | 不自動猜日期；只提供表單補齊入口 | 不產生可確認提議 |

- [ ] sanitized 再次經 `service.propose()`；Forbidden、Conflict、超出 schema、已取消 booking、revision 落後都不得產生恢復草案。sanitize 不能接受 owner、confirmation、expected_version 等額外欄位。
- [ ] `app.py:proposal()` 回 `validation` 給欄位，原表單值保留；結構化表單錯誤可先只返回 validation，不必造 draft，因為前端仍有表單資料。訊息接續需求主要是 Mock 分支。
- [ ] 在 `mock.parse` 中，未知「下週一／週末」不要沿用舊日期假裝理解；回明確補日期提示並提供 ISO 或表單。不要為了 Demo 擴成未經驗證的全語意日期引擎。
- [ ] 錯誤文案保留「目前尚未修改預約」。只出現通用 help 時，顯示可操作的「用表單選時間」而非單純說可使用表單。

**關鍵回歸測試**（加入新檔案；使用既有 API helper）：

```python
from test_api import client_for, send


def test_invalid_time_creates_new_draft_and_can_continue(tmp_path):
    client = client_for(tmp_path)
    old = send(client, "預約冷氣維修 2030-01-08 10:00", "initial")["operation"]
    rejected = send(client, "改成 2030-01-08 15:00", "invalid")
    assert rejected["rejected"] is True
    assert rejected["validation"]["code"] == "unsupported_time"
    draft = rejected["operation"]
    assert draft["id"] != old["id"]
    assert draft["status"] == "draft"
    assert draft["payload"]["slot"] is None
    assert draft["payload"]["time"] is None
    stale = client.post(
        f"/api/operations/{old['id']}/confirm",
        json={"confirmation": old["confirmation"]},
    )
    assert stale.status_code == 409
    updated = send(client, "那就 2030-01-08 16:00", "corrected")["operation"]
    assert updated["status"] == "waiting_confirmation"
    assert updated["payload"]["slot"] == "2030-01-08T16:00:00+08:00"
    assert client.get("/api/state").json()["bookings"] == []
```

再加下列互不重複情境，各測真正狀態：已存在的兩筆預約中指定一筆改期，15:00 錯誤後保留相同 booking_id；過去日期新草案不得保留舊 slot；Forbidden 不產生草案；同 request_id 重送同一錯誤不新增第二個 draft；錯誤後「先不要」再只輸入時間不得復活草案。沿用 `client_for`／`send` 建測資，先確認原始版本會失敗，再實作。

- [ ] 跑 `uv run --no-env-file pytest -q tests/test_ux_validation.py tests/test_edge_cases.py tests/test_api.py tests/test_service.py tests/test_recovery.py`。
- [ ] 用 UI 重走報告 J06，確認自然修正成功、舊確認不能用；提交 T03。

## T04：直接改期與欄位旁錯誤

**Files:** `index.html`、`app.js:renderBookings/submitProposal/booking-form listener`、`style.css`；`tests/test_browser.py`。

**Interfaces:** 既有 `submitProposal(proposal)` 維持 request ID 重試行為。新增單一 inline 改期 editor，`#reschedule-form`、`#reschedule-date`、`#reschedule-time`、`#reschedule-error`；以選中卡片的 booking.id 作 closure／editor state，不讓使用者輸入任意 booking ID。

- [ ] 點「改期」只開啟該卡片下的日期／時段 editor，預填原日期時間並顯示「原時間」。這一步不送 `/api/proposals`，不取消其他草案。
- [ ] 同時只開一個 editor；選另一筆時切換並保留明確對象。卡片被 refresh 更新時不默默把使用者編輯中的日期重置。預約已被取消則停用 editor，顯示「這筆預約已取消，請重新查看目前安排」。
- [ ] 主按鈕「預覽改期」；副按鈕「返回」。合法後才傳完整 action、booking_id、slot；service 繼續讀取最新版本並做確認時競爭檢查。

```javascript
await submitProposal({
  action: "reschedule",
  booking_id: selectedBooking.id,
  slot: `${$("reschedule-date").value}T${$("reschedule-time").value}:00+08:00`,
});
```

`selectedBooking` 是目前 editor 持有、由 `state.bookings` 選出的資料；不能從 URL 或任意輸入合成。

- [ ] 建立與改期共用時段驗證邏輯：以 Taipei 當日設定 date.min；今天只允許還沒過的三個時段。跨午夜／日期變動／再次 focus 時更新；全日都過時提供明日最早時段，勿提交過去時間。
- [ ] 前端先用 `new Date(iso).getTime() > Date.now()` 和允許時段檢查，錯誤留在對應欄位旁；後端仍必須重驗。
- [ ] T03 的 `validation.field` 對應欄位加 `aria-invalid="true"` 與 `aria-describedby`。修正後清掉該欄位錯誤；焦點移到第一個無效欄位。HTTP 拒絕時也保留已填值。
- [ ] 確認單改期顯示「原時間 → 新時間」。原時間來自目前可見 booking，若版本已變，標示「預約已有更新，請重新查看」，不能拿歷史收據當即時值。
- [ ] 文案「建立待確認操作」改「預覽預約」；下方說「下一步會請你確認」。

**驗收流程與斷言**：

```python
# 接在建立並確認一筆預約的 browser test 後。
page.get_by_role("button", name="改期", exact=True).click()
expect(page.locator("#reschedule-form")).to_be_visible()
page.locator("#reschedule-date").fill("2030-01-09")
page.locator("#reschedule-time").select_option("16:00")
before = db_bookings(live_server)[0]
page.get_by_role("button", name="預覽改期", exact=True).click()
expect(page.get_by_role("button", name="確認改期預約", exact=True)).to_be_visible()
assert db_bookings(live_server)[0]["slot"] == before["slot"]
page.get_by_role("button", name="確認改期預約", exact=True).click()
expect(page.locator("#bookings")).to_contain_text("16:00")
assert db_bookings(live_server)[0]["version"] == before["version"] + 1
```

另測過去日期：送出後 `aria-invalid` 正確、焦點在日期、欄位文字仍在、DB 不變、沒有送新 mutation。使用 page request 監聽計數比對前後，不靠 sleep。

- [ ] 跑 `tests/test_browser.py` 和 `tests/test_api.py`；截改期前後時間比較、日期錯誤畫面；提交 T04。

## T05：確認入口、倒數與過期狀態

**Files:** `index.html`、`app.js:renderConfirmation/confirmOperation/sendPending`、`style.css`；`tests/test_browser.py`、`tests/test_service.py`。

**Interfaces:** 沿用 server `op.expires`（秒）。新增 `#confirmation-next` 連結／按鈕、`#confirmation-expiry`；指向 `#confirmation-panel`。client countdown 只影響呈現，不修改 expires 或 confirmation。

- [ ] 有新 waiting_confirmation 時，在輸入框旁顯示「已準備好，查看確認單」。點擊後滚動到確認單並把焦點放在可程式 focus 的標題，讓使用者先閱讀，而不是直接 focus 最終提交。
- [ ] 手機改成主要由外頁捲動。近期對話顯示於主流程，較早訊息放「查看先前對話」；不讓固定高度內捲動區擋住去確認單的路。桌面可保留對話內捲動，但要保有明確下一步。
- [ ] 倒數格式：「請在 04:59 內確認」。到 0 切換「確認已過期，預約尚未修改」並移除／停用確認動作，提供「重新填寫」與「放棄」。
- [ ] 每秒只更新 countdown 節點、disabled 狀態；不要每秒 `replaceChildren()` 重建整張卡、丟失 focus 或讓讀屏重讀。
- [ ] 頁面重新可見／視窗 focus 時重算 Date.now；若伺服器與用戶時間差導致後端拒絕，立即 refresh 權威狀態并显示过期，不能自动 retry confirm。
- [ ] 「重新填寫」只把項目／日期填到 T04 editor；使用者按預覽後才新建草案。旧 token 絕不回填。過期原時間需重新驗證。

倒數函式示例：

```javascript
function remainingConfirmationSeconds(expires, nowMs = Date.now()) {
  return Math.max(0, Math.ceil(expires - nowMs / 1000));
}
```

以 `op.id` 綁定目前 countdown 控制器；換操作或無待辦時清理舊 timer。過期時依原 focus 所在位置更新：若原 focus 在確認按鈕，移到過期說明，不丟回 body。

**驗收**：用 Playwright clock 快轉測前端過期，不等真實五分鐘；啟用測試套件中實際安裝版本支援的 `page.clock`，若不支援則用既有可注入時間的測試設計，勿改生產時鐘。

```python
page.clock.install()
send(page, "預約冷氣維修，明天 10:00")
expect(page.get_by_role("button", name="確認建立預約", exact=True)).to_be_visible()
page.clock.fast_forward(301_000)
expect(page.locator("#confirmation-expiry")).to_contain_text("確認已過期")
expect(page.get_by_role("button", name="確認建立預約", exact=True)).to_have_count(0)
assert db_bookings(live_server) == []
```

若選 disabled 方案，對應改成 `to_be_disabled()`；兩方案只採一種，不寫同時都可能成立的寬鬆測試。建議採移除按鈕＋focus 遷移。

- [ ] server 過期測試使用 `BookingService(clock=...)` 注入時鐘，確認 300 秒界線後 409、無寫入。這與 browser clock 的 UX 測試分開。
- [ ] 390×844 上從新提議按「查看確認單」後，卡片標題在可視區、focus 正確；沒有任何自動提交請求。
- [ ] 跑 `tests/test_browser.py tests/test_service.py tests/test_recovery.py`；提交 T05。

## T06：結果就地呈現與有效／歷史分組

**Files:** `app.js:renderConfirmation/renderBookings/renderEvents`、`index.html`、`style.css`；`tests/test_browser.py`。

**Interfaces:** 依現有 `state.operations`、`state.bookings`、`receipt` 決定展示。新增 `#booking-history` details。`#booking-count` 固定代表有效數；`#bookings` 只容納有效預約。

- [ ] 完成確認後，確認區短暫／直到下次需求顯示成功摘要：「已建立預約／已改期／已取消」＋項目與時間＋「查看目前安排」；只接受 committed 與對應 receipt。
- [ ] 操作未知顯示「正在查證，請勿重做」和現有 recover 動作；禁止將 15 秒網路 timeout 當成失敗自動重送。
- [ ] 新增、改期成功在對應卡片附近提示；取消後有效區顯示「目前沒有有效預約」與預覽新預約入口。
- [ ] 已取消卡移到 `#booking-history`，摘要「已取消紀錄（N）」；預設收合。不得移除後端資料或更改統計定義。
- [ ] 技術事件列表放可展開的「操作明細」；主結果保留一段人話；ID／版本／原始收據仍可查，不讓長 ID 壓住主要日期。
- [ ] 中間「取消草案」與「取消預約」語詞分開，避免使用者以為原預約也被取消。

**驗收斷言**：

```python
expect(page.locator("#booking-count")).to_have_text("0")
expect(page.locator("#bookings")).to_contain_text("目前沒有有效預約")
expect(page.locator("#booking-history summary")).to_contain_text("已取消紀錄（1）")
rows = db_bookings(live_server)
assert len(rows) == 1 and rows[0]["status"] == "cancelled"
```

- [ ] 對「已提交，但回覆遺失」按 recover 兩次；有效筆數及版本都不增加。保留既有 receipt 現在／歷史狀態差異測試。
- [ ] 跑 `tests/test_browser.py tests/test_recovery.py tests/test_delivery.py`；提交 T06。

## T07：可讀、可點、可用鍵盤的流程

**Files:** `style.css`、`index.html`、`app.js:renderMessages`，必要時 `evaluation.css`；`tests/test_browser.py`。

- [ ] 手機主要正文目標至少 16px，輔助資訊至少 12px；主要按鈕／選單觸控框目標至少 44×44 CSS px。長範例可以換行，不能以 10px 小字塞下。
- [ ] 原生輸入／select／details 能保留就保留；確認單連結、改期 editor、欄位錯誤、歷史分組都納入 Tab 順序。可見 focus 不被 sticky 元件遮住。
- [ ] 新訊息才追加到 log，或以 request ID 更新既有 entry；查詢更新及倒數不得重建整段聊天造成重讀。保留使用者正在看舊訊息的捲動位置。
- [ ] 狀態摘要用一次性 `role=status` 宣告；倒數不用每秒 aria-live 朗讀；過期轉換一次宣告。
- [ ] Enter 送出、Shift+Enter 換行、IME 組字不誤送；沿用現有 `!e.isComposing` 保護。
- [ ] 檢查 390、680、900、1280 寬，200% zoom 與 reduced-motion；只有 JSON 等長內容區可橫向捲動，整頁不得溢出。
- [ ] 依實際字色與背景計算對比：一般文字至少 4.5:1、大字與必要圖形至少 3:1，记录量测值；不能只寫「看起來夠深」。

**尺寸驗收例**：

```python
for selector in ("#send", "#query-bookings"):
    box = page.locator(selector).bounding_box()
    assert box and box["width"] >= 44 and box["height"] >= 44
assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
```

- [ ] 手動鍵盤完成「建立→預覽→確認→改期→返回」；NVDA 或同級讀屏驗證一次新訊息、錯誤、完成提示。未能執行的項目明列未驗證，不以 AX tree 取代讀屏測試。
- [ ] 收斂本輪發現的問題後一次確認；跑 browser 回歸及 `node --check agent/static/app.js`；提交 T07。

## T08：讓評估證據容易看懂與再次找到

**Files:** `evaluation.html`、`evaluation.js`、`evaluation.css`、`tests/test_browser.py`。

**Interfaces:** 保留 GET `/api/evaluation` 及現有下载白名單。URL hash 使用 `#case=<encoded case>&strategy=<fixed|agent>`，只保存非敏感案例 ID／策略；未知 ID 忽略，不變成任意下載路徑。

- [ ] 在失敗说明區增加「查看未通過案例（1）」按鈕，將 `#case-filter` 設為 failed、render、展開唯一失敗並 focus summary。數量由 cases 計算，不能硬編碼未來永遠只有 1。
- [ ] 每個案例展開先顯示三行：要求、實際結果、為何通過／未通過。不得把模型原文改寫後偽稱原始結果；保留原文與 JSON details。
- [ ] 本輪失敗摘要明確：「沒有修改他人資料，但拒絕回覆未符合要求的 JSON 格式。」只有與已保存案例 ID／逐輪證據吻合才使用此句，其他案例從已保存欄位產生摘要，缺失時不編造原因。
- [ ] 預期／實際 DB 相同時，先顯示「資料庫結果一致」，仍可展開原始 JSON；不新增 LLM judge。
- [ ] 設定／讀回合法案例 hash，reload 能重新定位與展開；切換篩選不要無提示丟失目前閱讀位置。
- [ ] 保留模型、受測版本、8 題單次小樣本、保存結果不呼叫 API、DB 正確≠任務成功。若沒有可靠執行日期欄位，不能用本次網站體驗日期冒充評估日期。
- [ ] 手機比較表的長金額容許換行，欄位對齊不變；增補顯示標籤的可及名稱驗證。此次工具精確 label 定位未匹配，但 role combobox 正常，不應未經檢查就宣稱 label 一定缺失。

**驗收流程**：打開評估→按查看未通過案例→只有 1/16→失敗案例已展開→工具提議與原始 DB 可展開→reload 還是同案例→全部篩選仍 16→保存結果數值不變→390 寬無整頁溢出。測試沿用既有 `test_evidence_browser_filters_failure_and_preserves_mobile_layout`，新增直達和 reload 斷言，不重跑 API 評估。

- [ ] `node --check agent/static/evaluation.js`；`uv run --no-env-file pytest -q tests/test_browser.py tests/test_evaluation.py tests/test_holdout.py`；提交 T08。

## 最終驗證與交付

以下是**施工完成後應執行**的命令，本次規劃未執行，不得直接填「通過」。

```powershell
uv run --no-env-file pytest -q
uv run --no-env-file ruff check agent evals tests
uv run --no-env-file ruff format --check agent evals tests
node --check agent/static/app.js
node --check agent/static/evaluation.js
```

若 browser 測試因本機沒有 Chromium 而失敗，按專案 Playwright 安裝方式補齊，明確區分環境失敗與產品失敗。不得忽略所有 browser tests 來取得綠燈。

### 完成定義

- [ ] 全新桌面與手機首屏能看到起步入口，知道是免費模擬服務。
- [ ] 兩個查詢按鈕保留同一草案；手打新訊息造成取代時說清楚。
- [ ] 改期只用卡片日期選擇器也可完成；確認前 DB 不變。
- [ ] 15:00 出錯後可接續補 16:00；原 booking_id 保持；舊 token 仍被拒。
- [ ] 過去日期就地錯誤、已填資料保留。
- [ ] 手機一次點擊可抵達確認單；不再說右側；五分鐘過期主動更新。
- [ ] 成功／未知／已取消分得清，取消歷史仍可查。
- [ ] 回覆遺失恢復、重複 request、反悔、中斷、競爭改期與權限測試不退化。
- [ ] 評估數據及研究限制完整保留。
- [ ] 每項附實際命令與結果、前後畫面、剩餘限制；`docs/ux-review/2026-09-10/施工驗收紀錄.md` 可讓另一個工程代理重跑。

### 建議的施工交接提示詞

```text
請先讀 docs/ux-review/2026-09-10/使用體驗報告.md，
再讀 docs/superpowers/plans/2026-09-10-repair-desk-ux.md。
依計畫建議順序逐項執行，先處理 P1。
保留確認 token、intent revision、版本競爭、冪等與恢復保障，
不新增框架，不啟動付費模型，不刪既有資料或評估紀錄。
每項完成跑對應測試並以瀏覽器驗證，
將實際結果和截圖寫進施工驗收紀錄。
如果目前程式碼已變，先比對差異再調整實作；
不要把計畫中的未執行測試當成既有通過結果。
```
