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
  refreshSequence = 0,
  rescheduleDraft = null,
  uncertainOperationId = null,
  serverExpiredOperations = new Set(),
  confirmationTimer = null,
  countdownOperation = null;
const modeNames = {
  mock: "免費示範",
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
    year: "numeric",
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
  if (
    uncertainOperationId &&
    !state.operations.some(
      (op) =>
        op.id === uncertainOperationId &&
        ["waiting_confirmation", "executing"].includes(op.status),
    )
  )
    uncertainOperationId = null;
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
  $("confirmation-next").classList.toggle(
    "hidden",
    currentOp()?.status !== "waiting_confirmation",
  );
}
function renderModel() {
  for (const option of $("mode").options)
    option.disabled = option.value !== "mock" && !state.model_available;
  $("mode").disabled = sending;
  $("mode-badge").textContent = modeNames[$("mode").value];
  $("mode-help").textContent =
    $("mode").value === "mock"
      ? "目前操作不呼叫付費模型。"
      : "真實模型模式可能產生 API 費用；所有操作仍需你確認。";
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
  if (!state.messages.length) {
    list.replaceChildren();
    const welcome = node("div", undefined, "welcome");
    welcome.append(
      node("div", "↳", "welcome-symbol"),
      node("h3", "安排一筆模擬維修預約"),
      node("p", "選擇項目與時間，確認後才會保存。本示範不會聯絡維修人員。"),
      node("p", "支援今天、明天、後天或 YYYY-MM-DD；時段為 10:00、14:00、16:00。也可以用表單選日期。"),
    );
    list.append(welcome);
    return;
  }
  list.querySelector(".welcome")?.remove();
  const wanted = new Set();
  const messages = [...state.messages].sort((a, b) => a.revision - b.revision);
  let older = list.querySelector("#older-messages");
  if (messages.length > 4 && !older) {
    older = node("details", undefined, "older-messages");
    older.id = "older-messages";
    older.append(node("summary", "查看先前對話"), node("div"));
    list.prepend(older);
  } else if (messages.length <= 4 && older) {
    older.remove();
    older = null;
  }
  const olderCount = Math.max(0, messages.length - 4);
  for (const [messageIndex, message] of messages.entries()) {
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
      const key = `${message.request_id}-${speaker}`;
      wanted.add(key);
      let entry = list.querySelector(`[data-message-key="${CSS.escape(key)}"]`);
      if (!entry) {
        entry = node("div", undefined, "chat-entry " + speaker);
        entry.dataset.messageKey = key;
      }
      const destination = messageIndex < olderCount ? older.lastElementChild : list;
      if (entry.parentElement !== destination) destination.append(entry);
      const signature = JSON.stringify([text, message.response, speaker]);
      if (entry.dataset.renderSignature === signature) continue;
      entry.dataset.renderSignature = signature;
      entry.replaceChildren();
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
      if (speaker === "assistant" && message.response?.show_form)
        entry.append(
          button("用表單選時間", "secondary", () => openRelevantForm()),
        );
    }
  }
  for (const entry of list.querySelectorAll("[data-message-key]"))
    if (!wanted.has(entry.dataset.messageKey)) entry.remove();
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
    stopConfirmationTimer();
    const committed = state.operations[0]?.status === "committed" ? state.operations[0] : null;
    if (committed?.receipt?.booking) {
      const booking = committed.receipt.booking;
      const summary = node("div", undefined, "ticket-body committed-summary");
      summary.append(
        node("strong", `已${actions[committed.action].replace("預約", "")}預約`),
        node("p", `${booking.service} · ${when(booking.slot)}`),
        button("查看目前安排", "secondary", () => focusBookings()),
      );
      target.append(summary);
      return;
    }
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
  body.dataset.operationId = op.id;
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
  if (uncertainOperationId === op.id || op.status === "executing") {
    stopConfirmationTimer();
    body.append(
      node("div", "結果未知，正在查證。請勿重做或重新送出。", "notice"),
      button("查證結果與恢復", "primary", recover),
      button("放棄這次操作", "secondary", async () => {
        await api(`/api/operations/${op.id}/abandon`, {});
        await refresh();
      }),
    );
    target.append(body);
    return;
  }
  const expired =
    serverExpiredOperations.has(op.id) ||
    remainingConfirmationSeconds(op.expires) === 0;
  if (staleBooking)
    body.append(node("div", "預約資料或版本已變更，無法依這張確認單提交。請重新提出操作。", "notice error"));
  const expiry = node("div", undefined, "ticket-meta");
  expiry.id = "confirmation-expiry";
  expiry.dataset.expired = String(expired);
  body.append(expiry);
  const controls = node("div", undefined, "ticket-buttons");
  if (op.status === "waiting_confirmation" && !expired) {
    const confirm = button("確認" + actions[op.action], "primary", () =>
      confirmOperation(op),
    );
    confirm.dataset.confirmAction = "true";
    confirm.disabled = confirming || sending || !!pendingRequest || staleBooking;
    controls.append(confirm);
  }
  if (op.status === "waiting_confirmation" && expired)
    controls.append(button("重新填寫", "primary", () => restoreOperation(op)));
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
  updateConfirmationExpiry(op);
  startConfirmationTimer(op);
}

function remainingConfirmationSeconds(expires, nowMs = Date.now()) {
  return Math.max(0, Math.ceil(expires - nowMs / 1000));
}
function confirmationExpired(op) {
  return (
    op?.status === "waiting_confirmation" &&
    (serverExpiredOperations.has(op.id) || remainingConfirmationSeconds(op.expires) === 0)
  );
}
function stopConfirmationTimer() {
  if (confirmationTimer) clearInterval(confirmationTimer);
  confirmationTimer = null;
  countdownOperation = null;
}
function updateConfirmationExpiry(op) {
  const target = $("confirmation-expiry");
  if (!target || currentOp()?.id !== op.id) return;
  const remaining = serverExpiredOperations.has(op.id)
    ? 0
    : remainingConfirmationSeconds(op.expires);
  target.textContent = remaining
    ? `操作 ${op.id.slice(0, 10)} · 請在 ${String(Math.floor(remaining / 60)).padStart(2, "0")}:${String(remaining % 60).padStart(2, "0")} 內確認`
    : "確認已過期，預約尚未修改";
  if (!remaining && target.dataset.expired !== "true") {
    const moveFocus = document.activeElement?.dataset.confirmAction === "true";
    target.dataset.expired = "true";
    renderConfirmation();
    renderEvents();
    $("confirmation-expiry").setAttribute("role", "status");
    if (moveFocus) {
      $("confirmation-expiry").tabIndex = -1;
      $("confirmation-expiry").focus();
    }
  }
}
function startConfirmationTimer(op) {
  if (op.status !== "waiting_confirmation" || countdownOperation === op.id) return;
  stopConfirmationTimer();
  countdownOperation = op.id;
  confirmationTimer = setInterval(() => updateConfirmationExpiry(op), 1000);
}
function restoreOperation(op) {
  stopConfirmationTimer();
  const booking = state.bookings.find((item) => item.id === op.payload.booking_id);
  if (op.action === "reschedule" && booking) {
    openReschedule(booking);
    if (op.payload.slot) {
      rescheduleDraft.date = op.payload.slot.slice(0, 10);
      rescheduleDraft.time = op.payload.slot.slice(11, 16);
      renderBookings();
      $("reschedule-date")?.focus();
    }
  }
  else if (op.action === "cancel" && booking) {
    const card = document.querySelector(`[data-booking-id="${CSS.escape(booking.id)}"]`);
    const cancel = [...card.querySelectorAll("button")].find(
      (item) => item.textContent === "取消預約",
    );
    cancel?.focus();
    card?.scrollIntoView({ behavior: "smooth", block: "center" });
  } else {
    $("service").value = op.payload.service || "冷氣維修";
    if (op.payload.slot) {
      $("date").value = op.payload.slot.slice(0, 10);
      $("time").value = op.payload.slot.slice(11, 16);
    }
    document.querySelector(".booking-form-panel").open = true;
    $("date").focus();
  }
}
function renderBookings() {
  const target = $("bookings");
  const history = $("history-bookings");
  target.replaceChildren();
  history.replaceChildren();
  const active = state.bookings.filter((b) => b.status === "active");
  const cancelled = state.bookings.filter((b) => b.status === "cancelled");
  if (rescheduleDraft) {
    const edited = state.bookings.find((item) => item.id === rescheduleDraft.bookingId);
    if (!edited || edited.status !== "active") {
      rescheduleDraft = null;
      notice("這筆預約已取消，請重新查看目前安排。", true);
    }
  }
  $("booking-count").textContent = active.length;
  $("booking-history").querySelector("summary").textContent = `已取消紀錄（${cancelled.length}）`;
  if (!active.length) {
    target.append(
      node("p", "目前沒有有效預約。可用上方範例或表單預覽新預約。", "empty"),
    );
    target.append(button("預覽新預約", "secondary", () => openRelevantForm()));
  }
  for (const booking of state.bookings) {
    const card = node("article", undefined, "booking " + booking.status);
    card.dataset.bookingId = booking.id;
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
        button("改期", "text-button", () => openReschedule(booking)),
        button("取消預約", "text-button", () =>
          submitProposal({ action: "cancel", booking_id: booking.id }),
        ),
      );
      card.append(controls);
      if (rescheduleDraft?.bookingId === booking.id)
        card.append(buildRescheduleEditor(booking));
    }
    (booking.status === "active" ? target : history).append(card);
  }
}

function taipeiDate(date = new Date()) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Taipei",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}
function openReschedule(booking) {
  const current = rescheduleDraft?.bookingId === booking.id ? rescheduleDraft : null;
  rescheduleDraft = {
    bookingId: booking.id,
    originalSlot: booking.slot,
    date: current?.date || booking.slot.slice(0, 10),
    time: current?.time || booking.slot.slice(11, 16),
    error: current?.error || "",
    field: current?.field || "",
  };
  renderBookings();
  $("reschedule-date")?.focus();
}
function buildRescheduleEditor(booking) {
  const form = node("form", undefined, "reschedule-form");
  form.id = "reschedule-form";
  form.append(node("p", `原時間：${when(booking.slot)}`, "form-help"));
  const dateLabel = node("label", "新日期（台北）");
  dateLabel.htmlFor = "reschedule-date";
  const date = node("input");
  date.id = "reschedule-date";
  date.type = "date";
  date.max = "9999-12-31";
  date.required = true;
  date.min = taipeiDate();
  date.value = rescheduleDraft.date;
  const timeLabel = node("label", "新時段");
  timeLabel.htmlFor = "reschedule-time";
  const time = node("select");
  time.id = "reschedule-time";
  for (const value of ["10:00", "14:00", "16:00"]) {
    const option = node("option", value);
    option.value = value;
    time.append(option);
  }
  time.value = rescheduleDraft.time;
  const error = node("span", rescheduleDraft.error, "field-error");
  error.id = "reschedule-error";
  for (const input of [date, time]) {
    input.setAttribute("aria-describedby", "reschedule-error");
    if (rescheduleDraft.field === (input === date ? "date" : "time"))
      input.setAttribute("aria-invalid", "true");
    input.addEventListener("input", () => {
      rescheduleDraft.date = date.value;
      rescheduleDraft.time = time.value;
      rescheduleDraft.error = "";
      rescheduleDraft.field = "";
      input.removeAttribute("aria-invalid");
      error.textContent = "";
    });
  }
  const controls = node("div", undefined, "booking-controls");
  controls.append(
    button("預覽改期", "primary", async () => {
      rescheduleDraft.date = date.value;
      rescheduleDraft.time = time.value;
      if (!validateSlot(date, time, error)) return;
      await submitProposal({
        action: "reschedule",
        booking_id: booking.id,
        slot: `${date.value}T${time.value}:00+08:00`,
      });
    }),
    button("返回", "secondary", () => {
      const bookingId = rescheduleDraft.bookingId;
      rescheduleDraft = null;
      renderBookings();
      const card = document.querySelector(`[data-booking-id="${CSS.escape(bookingId)}"]`);
      [...card.querySelectorAll("button")]
        .find((item) => item.textContent === "改期")
        ?.focus();
    }),
  );
  form.append(dateLabel, date, timeLabel, time, error, controls);
  form.addEventListener("submit", (event) => event.preventDefault());
  return form;
}
function validateSlot(date, time, error) {
  date.min = taipeiDate();
  const allowed = ["10:00", "14:00", "16:00"];
  let field = "";
  let message = "";
  const timestamp = new Date(`${date.value}T${time.value}:00+08:00`).getTime();
  if (date.value && !/^\d{4}-\d{2}-\d{2}$/.test(date.value)) {
    field = "date";
    message = "年份必須為四位數，請重新選擇日期。";
  } else if (!date.value || !Number.isFinite(timestamp) || timestamp <= Date.now()) {
    field = "date";
    message = "請選擇尚未過去的日期與時段。";
  } else if (!allowed.includes(time.value)) {
    field = "time";
    message = "請選擇 10:00、14:00 或 16:00。";
  }
  for (const input of [date, time]) input.removeAttribute("aria-invalid");
  error.textContent = message;
  if (!field) return true;
  const input = field === "date" ? date : time;
  input.setAttribute("aria-invalid", "true");
  input.focus();
  if (rescheduleDraft) Object.assign(rescheduleDraft, { error: message, field });
  return false;
}
function openRelevantForm() {
  const op = currentOp();
  const booking = state.bookings.find((item) => item.id === op?.payload.booking_id);
  if (booking && op?.action === "reschedule") openReschedule(booking);
  else {
    if (op?.payload.service) $("service").value = op.payload.service;
    if (op?.payload.slot) {
      $("date").value = op.payload.slot.slice(0, 10);
      $("time").value = op.payload.slot.slice(11, 16);
    } else if (op?.payload.date) {
      $("date").value = op.payload.date;
    }
    document.querySelector(".booking-form-panel").open = true;
    $("date").focus();
  }
}
function renderEvents() {
  const target = $("events");
  target.replaceChildren();
  const latest = state.operations[0];
  const result = $("result");
  result.replaceChildren();
  if (latest?.id === uncertainOperationId) {
    result.textContent = "結果未知，正在查證。請勿重做；先查證原操作。";
  } else if (!latest) {
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
  } else if (confirmationExpired(latest)) {
    result.textContent =
      "確認已過期，預約尚未修改。請在確認單按「重新填寫」後，再確認新的操作。";
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
    if (result.rejected) {
      notice(result.text, true);
    }
    await refresh();
    if (result.rejected) applyValidation(result.validation, request);
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
function applyValidation(validation, request) {
  if (!validation) return;
  const isReschedule =
    request.path === "/api/proposals" &&
    request.body.proposal.action === "reschedule";
  if (isReschedule && rescheduleDraft) {
    rescheduleDraft.error = $("notice-text").textContent;
    rescheduleDraft.field = validation.field;
  }
  const prefix = isReschedule ? "reschedule-" : "";
  const field = validation.field === "slot" ? "date" : validation.field;
  const input = $(`${prefix}${field}`);
  const error = $(`${prefix}${prefix ? "error" : `${field}-error`}`);
  if (input) {
    input.setAttribute("aria-invalid", "true");
    input.focus();
  }
  if (error) error.textContent = $("notice-text").textContent;
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
    uncertainOperationId = null;
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
    if (error.status === 409) {
      if (error.message.includes("確認已過期")) serverExpiredOperations.add(op.id);
      await refresh();
    }
    else if (!error.status) uncertainOperationId = op.id;
    notice(
      error.status
        ? error.message
        : "連線中斷，結果未知。請查證原操作，避免重新建立。",
      true,
    );
  } finally {
    confirming = false;
    renderConfirmation();
    renderEvents();
  }
}
async function recover() {
  await api("/api/recover", {});
  clearNotice();
  await refresh();
  uncertainOperationId = null;
  renderConfirmation();
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
async function focusBookings() {
  $("bookings-heading").tabIndex = -1;
  $("bookings-heading").focus();
  $("bookings-heading").scrollIntoView({ behavior: "smooth", block: "start" });
}
async function queryBookings() {
  try {
    await refresh();
    const count = state.bookings.filter((booking) => booking.status === "active").length;
    notice(`目前有 ${count} 筆有效預約。${currentOp() ? "待確認內容已保留。" : ""}`);
    await focusBookings();
  } catch (error) {
    notice(error.message, true);
  }
}
$("query-bookings").addEventListener("click", queryBookings);
$("refresh").addEventListener("click", queryBookings);
$("confirmation-next").addEventListener("click", () => {
  $("confirmation-heading").tabIndex = -1;
  $("confirmation-heading").focus();
  $("confirmation-panel").scrollIntoView({ behavior: "smooth", block: "start" });
});
$("recover").addEventListener("click", () =>
  recover().catch((e) => notice(e.message, true)),
);
$("booking-form").addEventListener("submit", (e) => {
  e.preventDefault();
  if (!validateSlot($("date"), $("time"), $("date-error"))) return;
  submitProposal({
    action: "create",
    service: $("service").value,
    slot: `${$("date").value}T${$("time").value}:00+08:00`,
  });
});
const tomorrow = new Date(Date.now() + 86400000);
$("date").min = taipeiDate();
$("date").value = taipeiDate(tomorrow);
for (const id of ["date", "time"])
  $(id).addEventListener("input", () => {
    $(id).removeAttribute("aria-invalid");
    $(`${id}-error`).textContent = "";
  });
window.addEventListener("focus", () => {
  updateDateControls();
  if (currentOp()) updateConfirmationExpiry(currentOp());
});
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) {
    updateDateControls();
    if (currentOp()) updateConfirmationExpiry(currentOp());
  }
});
function updateDateControls() {
  const today = taipeiDate();
  $("date").min = today;
  const remainingToday = ["10:00", "14:00", "16:00"].some(
    (time) => new Date(`${today}T${time}:00+08:00`).getTime() > Date.now(),
  );
  if ($("date").value === today && !remainingToday)
    $("date").value = taipeiDate(new Date(Date.now() + 86400000));
}
for (const id of ["date", "time"])
  $(id).addEventListener("focus", updateDateControls);
refresh().catch((e) => notice("無法載入工作台：" + e.message, true));
