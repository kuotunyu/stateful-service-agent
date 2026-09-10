# 看懂維修預約流程

這個作品讓你用對話安排維修。系統先列出確認單，你確認後才保存；反悔或遇到逾時時，也能核對預約到底有沒有改變。

## 看實際操作：19 秒

[下載操作影片（WebM、無聲）](https://raw.githubusercontent.com/kuotunyu/stateful-service-agent/main/docs/demo/repair-desk-demo.webm)

下載後開啟影片，留意三件事：

- **建立預約**：先看到確認單，按確認後才出現在目前預約。
- **使用者反悔**：放棄尚未確認的操作，不會多出一筆預約。
- **模擬故障**：回覆遺失或服務重啟後，查回真正的結果，避免重複建立。

這是免費示範模式的實際操作錄影，不是與真實模型對話的錄影。

## 看懂原因：52 秒

[下載中文解說動畫（MP4、無聲字卡）](https://raw.githubusercontent.com/kuotunyu/stateful-service-agent/main/docs/demo/timeout-explainer/timeout-is-not-failure.mp4)

動畫解釋一個問題：**沒有收到成功回覆，為什麼不能直接再預約一次？** 因為資料可能已經保存，系統應先查原本的紀錄。這是原理解說，與上面的實際操作錄影不同。

<details>
<summary>給工程讀者：資料庫證據與重製方式</summary>

[六個 SQLite 檢查點](checkpoints.json)記錄的預約筆數依序為 **0、1、1、2、2、3**：

| 檢查點 | 預約筆數 |
|---|---|
| 預覽，尚未確認 | 0 |
| 確認建立 | 1 |
| 另一筆草案反悔 | 1 |
| 提交後回覆遺失，再查證 | 2 |
| 提交前逾時 | 2 |
| 重啟後恢復 | 3 |

最後三筆均為版本 1。測試直接查詢資料庫，不只依畫面文字判定成功。

從專案根目錄重製錄影：

```powershell
uv run --no-env-file python scripts/record_demo.py
```

僅啟停臨時測試程序，不呼叫 API。輸出在 `artifacts/demo-2026-09-10/`；目錄存在時拒絕覆寫。

動畫文字稿、來源與重製方式見 [動畫說明](timeout-explainer/README.md)。

</details>
