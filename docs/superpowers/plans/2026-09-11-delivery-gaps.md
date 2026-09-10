# 展示缺口與 CI 修正

使用者已同意四項範圍，依序實作，不重跑付費模型。

- [x] 加入回歸檢查：確認單與預約卡顯示年份；過期時操作結果同步；評估頁連到第二輪並保留基線。
- [x] 修正日期格式、衍生過期提示與評估頁文字。
- [x] 新增 Windows GitHub Actions：鎖定依賴、安裝 Chromium、Ruff、JS 語法及 pytest；不提供金鑰、不部署。
- [x] 本機完整回歸、提交、同步遠端並查證 Actions 真正執行成功。

歷史模型報告與原始證據保持原樣；CI 成功不等於新增模型能力評估或讀屏通過。

驗證：本機與 Windows CI 均為 130 passed。首次 CI 發現初始化完成前送出訊息會卡住，已補延遲載入反例並修正。程式提交 9fc72b0；[遠端成功紀錄](https://github.com/kuotunyu/stateful-service-agent/actions/runs/34518455467)。
