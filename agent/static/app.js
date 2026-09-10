"use strict";
const $ = (id) => document.getElementById(id);
const labels = {
  draft: "操作草案",
  waiting_confirmation: "等待確認",
  executing: "執行中／待查證",
  committed: "已提交",
  failed: "失敗",
  cancelled: "操作已取消",
  unknown: "結果待查證",
};
const actions = {
  create: "建立預約",
  reschedule: "改期預約",
  cancel: "取消預約",
};
let state,
  csrf = "",
  pendingRequest = null,
  sending = false,
  confirming = false,
  sendSequence = 0,
  refreshSequence = 0;
const modeNames = {
  mock: "MOCK",
  fixed: "固定流程 + LLM",
  agent: "單一 Agent",
  form: "表單",
};
function node(tag, text, className) {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  if (className) el.className = className;
  return el;
}
function notice(text, error = false) {
  $("notice-text").textContent = text;
  $("notice").className = "notice" + (error ? " error" : "");
}
function clearNotice() {
  $("notice").className = "notice hidden";
  $("retry").classList.add("hidden");
}
async function api(path, body) {
  const response = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers:
      body === undefined
        ? {}
        : { "Content-Type": "application/json", "X-CSRF-Token": csrf },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(15000),
  });
  const result = await response.json();
  if (!response.ok) {
    const error = new Error(
      typeof result.detail === "string"
        ? result.detail
        : "輸入內容不符合格式，請檢查後再試。",
    );
    error.status = response.status;
    throw error;
  }
  return result;
}
function when(slot) {
  if (!slot) return "尚未指定";
  return new Intl.DateTimeFormat("zh-TW", {
    timeZone: "Asia/Taipei",
    month: "2-digit",
    day: "2-digit",
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(slot));
}
function badge(status) {
  return node("span", labels[status] || status, "status " + status);
}
function button(text, className, onClick) {
  const b = node("button", text, className);
  b.type = "button";
  b.addEventListener("click", () =>
    Promise.resolve(onClick()).catch((e) => notice(e.message, true)),
  );
  return b;
}
async function refresh() {
  const seq = ++refreshSequence;
  const next = await api("/api/state");
  if (seq !== refreshSequence) return;
  state = next;
  csrf = next.csrf;
  render();
}
function render() {
  $("identity").textContent = "示範使用者 / " + state.identity;
  renderModel();
  renderMessages();
  renderConfirmation();
  renderBookings();
  renderEvents();
}
function renderModel() {
  for (const option of $("mode").options)
    option.disabled = option.value !== "mock" && !state.model_available;
  $("mode").disabled = sending;
  $("mode-badge").textContent = modeNames[$("mode").value];
  const usage = state.model_usage;
  $("model-usage").textContent = usage
    ? `${state.model_name} · 累計 ${usage.requests}/${usage.max_requests} 次（含評估）。已知用量 USD ${usage.actual_usd.toFixed(5)}；保守預留 ${usage.reserved_usd.toFixed(4)}/${usage.budget_usd.toFixed(2)}。${usage.unknown_requests} 次用量待查證。`
    : state.model_available
      ? "模型已連接。所有操作仍需你確認。"
      : "真實模型未啟用；Mock 與表單可直接使用。";
  $("interrupt").classList.toggle("hidden", !interruptTarget());
}
function interruptTarget() {
  return pendingRequest?.path === "/api/messages"
    ? pendingRequest.body.request_id
    : state?.messages.findLast((message) => !message.response)?.request_id;
}
async function interruptMessage() {
  const target = interruptTarget();
  if (!target) return;
  $("interrupt").disabled = true;
  try {
    const result = await api(
      `/api/messages/${encodeURIComponent(target)}/interrupt`,
      {},
    );
    ++sendSequence;
    pendingRequest = null;
    sending = false;
    $("send").disabled = false;
    clearNotice();
    notice(result.text);
    await refresh();
  } finally {
    $("interrupt").disabled = false;
  }
}
function renderMessages() {
  const list = $("messages");
  const nearBottom =
    list.scrollHeight - list.scrollTop - list.clientHeight < 90;
  list.replaceChildren();
  if (!state.messages.length) {
    const welcome = node("div", undefined, "welcome");
    welcome.append(
      node("div", "↳", "welcome-symbol"),
      node("h3", "今天需要安排什麼維修？"),
      node("p", "告訴我維修項目與時間。你可以隨時更改想法，準備好後再確認。"),
      node("p", "可選 Mock 範例句型或已啟用的真實模型；所有資料都是模擬預約。"),
    );
    list.append(welcome);
    return;
  }
  for (const message of state.messages) {
    let userText = message.text;
    try {
      const p = JSON.parse(userText);
      if (p.action)
        userText = [actions[p.action], p.service, p.slot ? when(p.slot) : null]
          .filter(Boolean)
          .join(" · ");
    } catch {}
    for (const [speaker, text] of [
      ["user", userText],
      [
        "assistant",
        message.response?.text ||
          "這則訊息尚待處理；如程序剛重啟，請重新查詢。",
      ],
    ]) {
      const entry = node("div", undefined, "chat-entry " + speaker);
      entry.append(
        node(
          "span",
          speaker === "user"
            ? "你"
            : "預約助手 · " +
                (message.response?.superseded
                  ? "已被新訊息取代"
                  : message.response?.interrupted
                    ? "已中斷"
                    : !message.response
                      ? "處理中"
                      : modeNames[message.response?.mode || "mock"]),
          "speaker",
        ),
        node("div", text, "bubble"),
      );
      if (speaker === "assistant" && message.response?.response_kind === "model_text") {
        entry.insertBefore(
          node("span", "模型回覆（內容未經查證）", "speaker"),
          entry.querySelector(".bubble"),
        );
        if (message.response.verification?.text)
          entry.append(node("div", message.response.verification.text, "verification"));
      }
      list.append(entry);
    }
  }
  if (nearBottom || sending) list.scrollTop = list.scrollHeight;
}
function currentOp() {
  return state.operations.find((op) =>
    ["draft", "waiting_confirmation", "executing"].includes(op.status),
  );
}
function renderConfirmation() {
  const target = $("confirmation");
  target.replaceChildren();
  const op = currentOp();
  if (!op) {
    target.append(
      node(
        "p",
        "目前沒有待確認操作。先在對話中提出需求，或使用下方表單。",
        "empty",
      ),
    );
    return;
  }
  const body = node("div", undefined, "ticket-body");
  body.append(
    node("div", actions[op.action], "ticket-action"),
    badge(op.status),
  );
  const dl = node("dl", undefined, "ticket-data");
  const booking =
    op.action === "create"
      ? null
      : state.bookings.find((item) => item.id === op.payload.booking_id);
  const staleBooking =
    op.action !== "create" &&
    (!booking || booking.version !== op.expected_version);
  for (const [label, value] of [
    ["預約編號", op.payload.booking_id || "新預約"],
    ["維修項目", op.payload.service || booking?.service || "尚未指定"],
    ["原預約時間", booking ? when(booking.slot) : op.action === "create" ? "不適用" : "無法查證"],
    ["新預約時間", op.action === "cancel" ? "取消，不另排時間" : when(op.payload.slot)],
    ["預期版本", op.expected_version ?? "不適用"],
    ["時區", "Asia/Taipei · UTC+8"],
  ])
    dl.append(node("dt", label), node("dd", value));
  body.append(dl);
  const expired = Date.now() / 1000 >= op.expires;
  if (staleBooking)
    body.append(node("div", "預約資料或版本已變更，無法依這張確認單提交。請重新提出操作。", "notice error"));
  body.append(
    node(
      "div",
      `操作 ${op.id.slice(0, 10)} · ${expired ? "確認已過期，請重新提出" : "確認期限 " + new Date(op.expires * 1000).toLocaleTimeString("zh-TW", { hour12: false })}`,
      "ticket-meta",
    ),
  );
  const controls = node("div", undefined, "ticket-buttons");
  if (op.status === "waiting_confirmation" && !expired) {
    const confirm = button("確認" + actions[op.action], "primary", () =>
      confirmOperation(op),
    );
    confirm.disabled = confirming || sending || !!pendingRequest || staleBooking;
    controls.append(confirm);
  }
  if (op.status === "executing")
    controls.append(button("查證結果與恢復", "primary", recover));
  controls.append(
    button("放棄這次操作", "secondary", async () => {
      await api(`/api/operations/${op.id}/abandon`, {});
      clearNotice();
      await refresh();
    }),
  );
  body.append(controls);
  target.append(body);
}
function renderBookings() {
  const target = $("bookings");
  target.replaceChildren();
  const active = state.bookings.filter((b) => b.status === "active");
  $("booking-count").textContent = active.length;
  if (!state.bookings.length) {
    target.append(
      node("p", "尚未安排預約。確認操作後，預約會顯示在這裡。", "empty"),
    );
    return;
  }
  for (const booking of [...state.bookings].sort(
    (a, b) => (a.status === "cancelled") - (b.status === "cancelled"),
  )) {
    const card = node("article", undefined, "booking " + booking.status);
    const top = node("div", undefined, "booking-top");
    top.append(
      node("h3", booking.service),
      node(
        "span",
        booking.status === "active" ? "已預約" : "預約已取消",
        "status " + (booking.status === "active" ? "committed" : "cancelled"),
      ),
    );
    card.append(
      top,
      node("div", when(booking.slot), "when"),
      node(
        "p",
        `預約 ${booking.id.slice(0, 10)} · 版本 ${booking.version}`,
        "booking-id",
      ),
    );
    if (booking.status === "active") {
      const controls = node("div", undefined, "booking-controls");
      controls.append(
        button("改期", "text-button", () =>
          submitProposal({ action: "reschedule", booking_id: booking.id }),
        ),
        button("取消預約", "text-button", () =>
          submitProposal({ action: "cancel", booking_id: booking.id }),
        ),
      );
      card.append(controls);
    }
    target.append(card);
  }
}
function renderEvents() {
  const target = $("events");
  target.replaceChildren();
  const latest = state.operations[0];
  const result = $("result");
  result.replaceChildren();
  if (!latest) {
    result.textContent =
      "尚無操作結果。每次確認後，這裡會顯示資料庫中的提交狀態。";
  } else if (latest.status === "committed") {
    const booking = latest.receipt.booking;
    result.append(
      node("strong", "已查證：" + actions[latest.action] + "完成。"),
      node(
        "div",
        `${booking.service} · ${when(booking.slot)} · ${booking.status === "active" ? "已預約" : "已取消"}`,
      ),
      node(
        "div",
        `收據 ${latest.id} / 預約版本 ${booking.version}。此為該次提交收據；目前狀態請見預約區。`,
      ),
    );
  } else if (latest.status === "failed") {
    result.textContent = "操作失敗，未提交變更。" + latest.reason;
  } else if (latest.status === "cancelled") {
    result.textContent =
      "這次操作已取消。" +
      (latest.reason || "") +
      "。已提交的其他預約不受影響。";
  } else if (latest.status === "executing") {
    result.textContent =
      "執行結果尚待查證。請按「查證結果與恢復」，系統會先查提交收據，再判斷是否恢復原操作。";
  } else {
    result.textContent =
      latest.status === "draft"
        ? "草案尚缺資料，預約尚未修改。"
        : "正在等待你的確認，預約尚未修改。";
  }
  for (const event of state.events.slice(0, 12)) {
    const item = node("li", undefined, "event");
    const time = node(
      "time",
      new Date(event.created * 1000).toLocaleTimeString("zh-TW", {
        hour12: false,
      }),
    );
    const content = node("div");
    content.append(
      node(
        "span",
        `${labels[event.kind] || event.kind} · ${(event.operation_id || "").slice(0, 8)}`,
        "event-kind",
      ),
      node("p", event.detail),
    );
    item.append(time, content);
    target.append(item);
  }
}
async function sendMessage(text) {
  if (sending) return;
  if (
    pendingRequest?.path !== "/api/messages" ||
    pendingRequest.body.text !== text ||
    pendingRequest.body.mode !== $("mode").value
  )
    pendingRequest = {
      path: "/api/messages",
      body: { request_id: crypto.randomUUID(), text, mode: $("mode").value },
    };
  await sendPending();
}
async function submitProposal(proposal) {
  if (sending) return;
  if (
    pendingRequest?.path !== "/api/proposals" ||
    JSON.stringify(pendingRequest.body.proposal) !== JSON.stringify(proposal)
  )
    pendingRequest = {
      path: "/api/proposals",
      body: { request_id: crypto.randomUUID(), proposal },
    };
  await sendPending();
}
async function sendPending() {
  if (sending || !pendingRequest) return;
  const request = pendingRequest;
  const seq = ++sendSequence;
  sending = true;
  $("send").disabled = true;
  renderConfirmation();
  renderModel();
  clearNotice();
  try {
    const result = await api(request.path, request.body);
    if (seq !== sendSequence) return;
    pendingRequest = null;
    if (
      request.path === "/api/messages" &&
      $("message").value === request.body.text
    )
      $("message").value = "";
    if (result.rejected) notice(result.text, true);
    await refresh();
  } catch (error) {
    if (seq !== sendSequence) return;
    notice(
      error.status
        ? error.message
        : "連線中斷。重試會沿用原請求；送出不同訊息則表示新的意圖。",
      true,
    );
    if (error.status && error.status !== 409) pendingRequest = null;
    $("retry").classList.toggle("hidden", !pendingRequest);
  } finally {
    if (seq === sendSequence) {
      sending = false;
      $("send").disabled = false;
      renderConfirmation();
      renderModel();
    }
  }
}
async function confirmOperation(op) {
  confirming = true;
  renderConfirmation();
  clearNotice();
  try {
    const result = await api(`/api/operations/${op.id}/confirm`, {
      confirmation: op.confirmation,
      fault: $("fault").value,
    });
    $("fault").value = "none";
    await refresh();
    if (result.delivery === "unknown")
      notice(
        state.operations.find((item) => item.id === op.id)?.status ===
          "committed"
          ? "工具回覆逾時，但已從資料庫查證提交完成；不用重做。"
          : "工具回覆逾時，结果尚待查證。請查證原操作，或在提交前改變意圖。",
      );
  } catch (error) {
    notice(
      error.status
        ? error.message
        : "連線中斷，結果未知。請查證原操作，避免重新建立。",
      true,
    );
  } finally {
    confirming = false;
    renderConfirmation();
  }
}
async function recover() {
  await api("/api/recover", {});
  clearNotice();
  await refresh();
  notice("已完成查證；操作結果與目前預約已更新。");
}
$("chat-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const text = $("message").value.trim();
  if (text) sendMessage(text);
});
$("message").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    $("chat-form").requestSubmit();
  }
});
document
  .querySelectorAll("[data-prompt]")
  .forEach((b) =>
    b.addEventListener("click", () => sendMessage(b.dataset.prompt)),
  );
$("retry").addEventListener("click", () => sendPending());
$("mode").addEventListener("change", renderModel);
$("interrupt").addEventListener("click", () =>
  interruptMessage().catch((e) => notice(e.message, true)),
);
setInterval(() => {
  if (state && (sending || state.messages.some((message) => !message.response)))
    refresh().catch(() => {});
}, 2000);
$("refresh").addEventListener("click", () =>
  refresh().catch((e) => notice(e.message, true)),
);
$("recover").addEventListener("click", () =>
  recover().catch((e) => notice(e.message, true)),
);
$("booking-form").addEventListener("submit", (e) => {
  e.preventDefault();
  submitProposal({
    action: "create",
    service: $("service").value,
    slot: `${$("date").value}T${$("time").value}:00+08:00`,
  });
});
const tomorrow = new Date(Date.now() + 86400000);
$("date").value = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Taipei",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
}).format(tomorrow);
refresh().catch((e) => notice("無法載入工作台：" + e.message, true));
