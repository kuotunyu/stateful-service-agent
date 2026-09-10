# 逾時不等於失敗

[播放 52 秒中文解說動畫](timeout-is-not-failure.mp4) · [實際操作錄影](../repair-desk-demo.webm) · [SQLite 檢查點](../checkpoints.json)

這是使用 Manim Community 製作的無聲流程解說，中文字卡已直接放入畫面。它解釋本專案的交易與查證邊界，不是介面錄影，也不是新增的模型評估或端到端測試。

| 時間 | 文字稿與重點 |
|---|---|
| 00–06 秒 | 逾時不等於失敗：沒有收到成功回覆，能直接再建一次預約嗎？ |
| 06–15 秒 | 使用者確認後，程式檢查身分、版本與期限。模型只能提議。 |
| 15–24 秒 | 同一個 SQLite 交易保存預約變更與提交收據。 |
| 24–32 秒 | 回覆遺失時，介面顯示結果未知；資料庫其實已提交。 |
| 32–41 秒 | 沿用原操作 ID 查證，找到已提交收據便回傳既有結果，不另建預約。 |
| 41–52 秒 | 第 03 → 04 檢查點：原有 1 筆，本次新增 1 筆，共 2 筆；原預約不變。 |

最後的筆數、維修項目、日期與版本讀自 `docs/demo/checkpoints.json`。腳本在渲染前檢查新增恰好一個預約 ID、沒有重複 ID、原有預約不變；[驗證摘要](verification.json) 保存來源與影片雜湊、影片規格及關鍵影格。中間的封包、收據與交易圖是依 `agent/service.py` 設計繪製的示意，不是從事件追蹤重建的時間線。沒有宣稱任意外部 SaaS 的 exactly-once 保證。

## 重製

在專案根目錄使用以下 PowerShell 命令。需 `uv`、Windows 的 Microsoft JhengHei 字體；全程 Cairo CPU 渲染，不開預覽視窗、不呼叫模型，也不讀 `.env` 或操作預約服務。

```powershell
uv venv --python 3.12 artifacts/manim-env
uv pip install --python artifacts/manim-env/Scripts/python.exe -r docs/demo/timeout-explainer/requirements.txt
artifacts/manim-env/Scripts/python.exe -m manim render scripts/timeout_animation.py TimeoutIsNotFailure --renderer cairo -qm --format mp4 --media_dir artifacts/manim-render --disable_caching
```

輸出：`artifacts/manim-render/videos/timeout_animation/720p30/TimeoutIsNotFailure.mp4`。若環境已存在，可省略建立環境的第一行；避免重建其他專案環境。Manim 的套件依賴雖包含 OpenGL 支援，本片明確選用 Cairo。

[動畫原始碼](../../../scripts/timeout_animation.py)；這組工具依賴獨立於產品的 `pyproject.toml` 與 `.venv`。

工具參考：[Manim Community 安裝](https://docs.manim.community/en/stable/installation/uv.html)、[渲染與輸出設定](https://docs.manim.community/en/stable/guides/configuration.html)。
