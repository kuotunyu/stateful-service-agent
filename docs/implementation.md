# Stateful Service Agent — local implementation

Approved 2026-09-10. Workspace: `D:\AI-Portfolio\CC_github部隊\stateful-service-agent`.
Future repository: `kuotunyu/stateful-service-agent`; no remote creation or publication.

Goal: a repair booking UI whose reported outcome is backed by durable business state.
Python + FastAPI serves a static browser UI and SQLite. CPU only, synthetic data, no paid calls.
Model output proposes actions; server session identity, confirmation, policy and transactions
remain authoritative. No network or GPU model is used by the default mock.

## Execution checklist

- [x] Core: write failing behavioral tests in `tests/test_service.py`; implement
  `agent/db.py`, `agent/models.py`, `agent/service.py`; run `uv run pytest`.
  Cover CRUD, stale confirmations, cross-owner rejection, duplicate requests, slot/version conflicts.
- [x] Recovery: test before/after-commit lost responses and process termination using real SQLite;
  persist operation IDs, confirmation expiry, receipts and execution state. A transaction changes
  the booking and receipt together; recovery checks receipts before resuming authorized work.
- [x] Product: implement `agent/app.py`, `agent/mock.py`, and `agent/static/`.
  API tests verify server identity, CSRF, replay and multi-turn completion. Browser check verifies
  create/change/cancel, intent reversal, lost response and refresh with real API requests.
- [x] Evaluation: add bounded replay cases and two orchestration policies sharing tool access,
  confirmation rules, model interface and configuration. Compare DB snapshots and event records.
  Report mock engineering results separately. First real-model pilot completed after explicit
  USD 1 / 144-request authorization: 33 requests, USD 0.0100752 token cost; see
  `docs/evaluations/paid-pilot-01/report.md` for results and limitations.
- [x] Delivery: run all checks, inspect desktop/mobile screenshots, write concise README and
  failure examples, retain local source history and provide launch/demo commands.

## Commit boundary and risk decisions

`draft -> waiting_confirmation -> executing -> committed | failed`; uncommitted work may be
`cancelled`. Executing with an unavailable response is `unknown`, not a proven failure.
New user turns advance a durable intent revision before parsing; delayed proposals and commits
must match it. Confirmation binds operation, payload, revision, owner, booking version and expiry.
If the transaction commits first, reversal needs a separately confirmed cancellation operation.
If intent invalidation commits first, old work cannot commit. This is a serialized DB boundary,
not a claim that a mouse click can undo an already completed write.

Operations have stable IDs and receipts; duplicate message IDs bind to exact input. Retried
confirmation returns the existing result. Active-slot uniqueness and optimistic booking versions
prevent double booking and lost updates. Model/tool text is data and cannot set session identity,
confirm work, execute code, or bypass policy. No arbitrary tool dispatch or external retrieval.

UI direction: a blue-gray service desk, cyan accents, a yellow confirmation slip and receipt
timeline. Palette: ink #17324d, background #edf3f8, paper #ffffff, blue #126c9c,
yellow #fff0b3, muted #536a7e. Segoe UI/Microsoft JhengHei body, Bahnschrift display,
Consolas IDs. Desktop: conversation left, booking and confirmation right; narrow screens stack.
The receipt is the visual signature and carries real operation status, not decorative metrics.
