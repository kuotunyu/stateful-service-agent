"use strict";
const $ = (id) => document.getElementById(id);
const names = {
  split_washer_request: "多輪補齊洗衣機預約",
  reschedule_selected_service: "辨識多筆預約，只改洗衣機",
  cancel_selected_id: "取消指定編號，保留其他預約",
  reverse_reschedule: "改期後反悔，拒絕舊確認",
  query_active_filter: "只查有效預約",
  query_under_document_attack: "文件注入下查詢真實狀態",
  spoofed_owner_authorization: "拒絕偽造身分的取消要求",
  unsupported_evening_slot: "拒絕不支援的晚間時段",
};
let cases = [];
function node(tag, text, className) {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  if (className) el.className = className;
  return el;
}
function renderCases() {
  const filter = $("case-filter").value;
  const selected = cases.filter(
    (c) =>
      filter === "all" ||
      (filter === "failed" ? !c.task_success : c.strategy === filter),
  );
  $("case-count").textContent =
    `${selected.length} / ${cases.length} 個任務；展開查看每一步與資料庫結果。`;
  $("case-list").replaceChildren();
  for (const c of selected) {
    const card = node("details", undefined, "case");
    const heading = node(
      "summary",
      `${names[c.case] || c.case} · ${c.strategy === "fixed" ? "固定流程" : "單一 Agent"}`,
    );
    heading.append(
      node(
        "span",
        c.task_success ? "通過" : "未通過",
        "status " + (c.task_success ? "committed" : "failed"),
      ),
    );
    const body = node("div", undefined, "case-body");
    body.append(
      node(
        "p",
        `DB ${c.db_correct ? "正確" : "不符預期"} · 越權修改 ${c.unauthorized_changes} · 重複效果 ${c.duplicate_operations} · ${(c.latency_ms / 1000).toFixed(3)} 秒`,
      ),
    );
    c.turns.forEach((turn, i) => {
      body.append(
        node(
          "h3",
          `第 ${i + 1} 輪 · ${turn.step_ok ? "符合要求" : "未符合要求"}`,
        ),
        node("p", "使用者：" + turn.text),
        node("p", "模型回覆：" + turn.response),
      );
      const trace = node("details");
      trace.append(
        node("summary", "查看工具提議"),
        node("pre", JSON.stringify(turn.trace, null, 2)),
      );
      body.append(trace);
    });
    body.append(
      node("h3", "預期資料庫"),
      node("pre", JSON.stringify(c.expected, null, 2)),
      node("h3", "實際資料庫"),
      node("pre", JSON.stringify(c.actual, null, 2)),
    );
    card.append(heading, body);
    $("case-list").append(card);
  }
}
async function load() {
  const response = await fetch("/api/evaluation", {
    signal: AbortSignal.timeout(10000),
  });
  if (!response.ok)
    throw new Error(
      "無法讀取已保存的評估。請檢查本機服務與證據檔案後重新整理。",
    );
  const data = await response.json();
  const s = data.summary.strategies;
  $("run-info").textContent =
    "受測版本 " + data.freeze.source_commit.slice(0, 7);
  const metrics = [
    [
      "DB 最終狀態正確",
      (x) => `${Math.round(x.db_final_state_accuracy * x.tasks)}/${x.tasks}`,
    ],
    [
      "完整任務成功",
      (x) => `${Math.round(x.task_success_rate * x.tasks)}/${x.tasks}`,
    ],
    ["他人資料修改", (x) => x.unauthorized_changes],
    ["重複操作效果", (x) => x.duplicate_operations],
    ["任務延遲中位數", (x) => `${(x.latency_p50_ms / 1000).toFixed(3)} 秒`],
    ["p95（本組最大值）", (x) => `${(x.latency_p95_ms / 1000).toFixed(3)} 秒`],
    ["API 請求", (x) => x.usage.requests],
    ["Token 計算費用", (x) => `USD ${x.usage.actual_usd.toFixed(7)}`],
  ];
  for (const [label, value] of metrics) {
    const row = node("tr");
    const th = node("th", label);
    th.scope = "row";
    row.append(th, node("td", value(s.fixed)), node("td", value(s.agent)));
    $("comparison").append(row);
  }
  $("usage").textContent =
    `本輪 ${data.summary.usage.requests} 次 API，USD ${data.summary.usage.actual_usd.toFixed(6)}。此處是保存的評估結果，與工作台即時用量分開呈現。`;
  cases = data.cases;
  renderCases();
}
$("case-filter").addEventListener("change", renderCases);
load().catch((error) => {
  $("load-error").textContent = error.message;
  $("load-error").classList.remove("hidden");
});
