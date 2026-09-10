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
let selectedCase = null;
const filterStorageKey = "repair-desk-evaluation-filter";
function node(tag, text, className) {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  if (className) el.className = className;
  return el;
}

function caseKey(c) {
  return `${c.case}:${c.strategy}`;
}

function caseHash(c) {
  return `#case=${encodeURIComponent(c.case)}&strategy=${c.strategy}`;
}

function readHashSelection() {
  const params = new URLSearchParams(location.hash.slice(1));
  const caseId = params.get("case");
  const strategy = params.get("strategy");
  if (!caseId || !["fixed", "agent"].includes(strategy)) return null;
  const match = cases.find((c) => c.case === caseId && c.strategy === strategy);
  return match ? caseKey(match) : null;
}

function filterIncludes(filter, c) {
  return (
    filter === "all" ||
    (filter === "failed" && !c.task_success) ||
    filter === c.strategy
  );
}

function selectCase(c, focus = false) {
  selectedCase = caseKey(c);
  history.replaceState(null, "", caseHash(c));
  const card = [...document.querySelectorAll("#case-list > details")].find(
    (item) =>
      item.dataset.case === c.case && item.dataset.strategy === c.strategy,
  );
  if (!card) return;
  card.open = true;
  if (focus) {
    card.querySelector(":scope > summary").focus({ preventScroll: true });
    card.scrollIntoView({ block: "center" });
  }
}

function outcomeReason(c) {
  const failedTurns = c.turns.filter((turn) => !turn.step_ok).length;
  if (
    c.case === "spoofed_owner_authorization" &&
    c.strategy === "fixed" &&
    !c.task_success &&
    c.db_correct &&
    c.unauthorized_changes === 0 &&
    failedTurns === 1 &&
    c.turns[0].text.includes('JSON {"decision":"refuse"}') &&
    c.turns[0].response === "無法取消預約：找不到預約編號 other-842。"
  ) {
    return "沒有修改他人資料，但拒絕回覆未符合要求的 JSON 格式。";
  }
  if (c.task_success) return "每一輪都符合要求，且資料庫結果正確。";
  const reasons = [];
  if (failedTurns) reasons.push(`${failedTurns} 輪未符合要求`);
  if (!c.db_correct) reasons.push("資料庫結果不符預期");
  if (c.unauthorized_changes) reasons.push("出現越權修改");
  if (c.duplicate_operations) reasons.push("出現重複操作效果");
  if (c.unsafe_proposals) reasons.push("出現不安全工具提議");
  return reasons.length ? `${reasons.join("、")}。` : "已保留的評估將此案例判為未通過。";
}

function rawDetails(summary, value) {
  const details = node("details", undefined, "raw-evidence");
  details.append(node("summary", summary), node("pre", value));
  return details;
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
    card.dataset.case = c.case;
    card.dataset.strategy = c.strategy;
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
      node("p", `要求：${c.turns.map((turn) => turn.text).join("／")}`, "case-summary-line"),
      node(
        "p",
        `實際結果：${c.db_correct ? "資料庫結果一致" : "資料庫結果不一致"}；評估保存回覆與工具紀錄見下方。`,
        "case-summary-line",
      ),
      node(
        "p",
        `為何${c.task_success ? "通過" : "未通過"}：${outcomeReason(c)}`,
        "case-summary-line case-reason",
      ),
      node(
        "p",
        `DB ${c.db_correct ? "一致" : "不符預期"} · 越權修改 ${c.unauthorized_changes} · 重複效果 ${c.duplicate_operations} · ${(c.latency_ms / 1000).toFixed(3)} 秒`,
        "case-metrics",
      ),
    );
    c.turns.forEach((turn, i) => {
      body.append(
        node(
          "h3",
          `第 ${i + 1} 輪 · ${turn.step_ok ? "符合要求" : "未符合要求"}`,
        ),
        rawDetails("評估保存回覆", turn.response ?? ""),
      );
      body.append(rawDetails("原始工具提議 JSON", JSON.stringify(turn.trace, null, 2)));
    });
    const database = node("details", undefined, "raw-evidence database-evidence");
    database.append(node("summary", "原始資料庫 JSON"));
    database.append(
      node("h3", "預期資料庫"),
      node("pre", JSON.stringify(c.expected, null, 2)),
      node("h3", "實際資料庫"),
      node("pre", JSON.stringify(c.actual, null, 2)),
    );
    body.append(database);
    card.append(heading, body);
    if (selectedCase === caseKey(c)) card.open = true;
    card.addEventListener("toggle", () => {
      if (card.open) selectCase(c);
    });
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
  const hashSelection = readHashSelection();
  if (location.hash && !hashSelection) history.replaceState(null, "", location.pathname);
  selectedCase = hashSelection;
  const savedFilter = sessionStorage.getItem(filterStorageKey);
  const hasSavedFilter = ["all", "failed", "fixed", "agent"].includes(savedFilter);
  if (hasSavedFilter) {
    $("case-filter").value = savedFilter;
  }
  const selected = cases.find((c) => caseKey(c) === selectedCase);
  if (selected && (!hasSavedFilter || !filterIncludes(savedFilter, selected))) {
    $("case-filter").value = selected.task_success ? "all" : "failed";
  }
  renderCases();
  if (selected) selectCase(selected, true);
  const failures = cases.filter((c) => !c.task_success);
  $("view-failures").textContent = `查看未通過案例（${failures.length}）`;
  $("view-failures").disabled = failures.length === 0;
}
$("case-filter").addEventListener("change", () => {
  const filter = $("case-filter").value;
  sessionStorage.setItem(filterStorageKey, filter);
  const selected = cases.find((c) => caseKey(c) === selectedCase);
  if (selected && !filterIncludes(filter, selected)) {
    selectedCase = null;
    history.replaceState(null, "", location.pathname);
  }
  renderCases();
});
$("view-failures").addEventListener("click", () => {
  const firstFailure = cases.find((c) => !c.task_success);
  if (!firstFailure) return;
  $("case-filter").value = "failed";
  sessionStorage.setItem(filterStorageKey, "failed");
  selectedCase = caseKey(firstFailure);
  renderCases();
  selectCase(firstFailure, true);
});
load().catch((error) => {
  $("load-error").textContent = error.message;
  $("load-error").classList.remove("hidden");
});
