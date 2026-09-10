"""Authoritative policy and durable operations. No model calls inside transactions."""

import json
import secrets
import sqlite3
import time
import uuid
from datetime import date, datetime, timedelta, timezone

from pydantic import ValidationError

from agent.db import Database
from agent.models import Proposal

TAIPEI = timezone(timedelta(hours=8))


class Conflict(Exception):
    pass


class Forbidden(Exception):
    pass


class SlotValidationError(ValueError):
    def __init__(self, code, field, message):
        super().__init__(message)
        self.code, self.field = code, field


def uid():
    return uuid.uuid4().hex


class BookingService:
    def __init__(self, path, clock=time.time):
        self.db = Database(path)
        self.path = self.db.path
        self.clock = clock

    def _event(self, db, session, op, kind, detail):
        db.execute(
            "INSERT INTO events(session_id,operation_id,kind,detail,created) VALUES(?,?,?,?,?)",
            (session, op, kind, detail, self.clock()),
        )

    def new_session(self, owner):
        session = {
            "id": secrets.token_urlsafe(32),
            "owner": owner,
            "csrf": secrets.token_urlsafe(32),
            "revision": 0,
        }
        with self.db.connect(write=True) as db:
            db.execute("INSERT INTO sessions(id,owner,csrf) VALUES(:id,:owner,:csrf)", session)
        return session

    def _session(self, db, session):
        row = db.execute("SELECT * FROM sessions WHERE id=?", (session,)).fetchone()
        if row is None:
            raise Forbidden("工作階段不存在，請重新整理頁面。")
        return dict(row)

    def session(self, session):
        with self.db.connect() as db:
            return self._session(db, session)

    def conversation(self, session, before_revision):
        """Bounded persisted dialogue, without tokens, tool traces or operation objects."""
        with self.db.connect() as db:
            self._session(db, session)
            rows = db.execute(
                "SELECT text,response FROM messages WHERE session_id=? AND revision<? "
                "AND response IS NOT NULL ORDER BY id DESC LIMIT 8",
                (session, before_revision),
            ).fetchall()
        history = []
        for row in reversed(rows):
            response = json.loads(row["response"])
            if response.get("interrupted") or response.get("superseded"):
                continue
            history.append(
                {"user": row["text"][:2000], "assistant": response.get("text", "")[:2000]}
            )
        return history

    def _decode(self, row):
        result = dict(row)
        for field in ("payload", "receipt"):
            result[field] = json.loads(result[field]) if result[field] else None
        return result

    def _operation(self, db, session, op_id):
        who = self._session(db, session)
        row = db.execute("SELECT * FROM operations WHERE id=?", (op_id,)).fetchone()
        if row is None or row["session_id"] != session or row["owner"] != who["owner"]:
            raise Forbidden("無法存取這筆操作。")
        return self._decode(row)

    def operation(self, session, op_id):
        with self.db.connect() as db:
            return self._operation(db, session, op_id)

    def begin_turn(self, session, request_id, text):
        with self.db.connect(write=True) as db:
            who = self._session(db, session)
            if db.execute(
                "SELECT 1 FROM interrupted_requests WHERE session_id=? AND request_id=?",
                (session, request_id),
            ).fetchone():
                raise Conflict("這個請求已中斷，請用新訊息提出需求。")
            old = db.execute(
                "SELECT * FROM messages WHERE session_id=? AND request_id=?", (session, request_id)
            ).fetchone()
            if old:
                if old["text"] != text:
                    raise Conflict("重複請求編號的內容不同，請使用新的請求。")
                return {**dict(old), "replayed": True}
            previous = db.execute(
                "SELECT * FROM operations WHERE session_id=? ORDER BY created DESC, rowid DESC LIMIT 1",
                (session,),
            ).fetchone()
            revision = who["revision"] + 1
            db.execute("UPDATE sessions SET revision=? WHERE id=?", (revision, session))
            pending = db.execute(
                "SELECT id FROM operations WHERE session_id=? AND status IN ('draft','waiting_confirmation','executing')",
                (session,),
            ).fetchall()
            for op in pending:
                self._event(db, session, op["id"], "cancelled", "新訊息取代了尚未提交的操作。")
            db.execute(
                "UPDATE operations SET status='cancelled',reason=?,updated=? WHERE session_id=? AND status IN ('draft','waiting_confirmation','executing')",
                ("新意圖已取代", self.clock(), session),
            )
            db.execute(
                "INSERT INTO messages(session_id,request_id,text,revision,created) VALUES(?,?,?,?,?)",
                (session, request_id, text, revision, self.clock()),
            )
            return {
                "revision": revision,
                "replayed": False,
                "response": None,
                "previous": self._decode(previous) if previous else None,
            }

    def interrupt_turn(self, session, request_id):
        with self.db.connect(write=True) as db:
            who = self._session(db, session)
            db.execute(
                "INSERT OR IGNORE INTO interrupted_requests VALUES(?,?)", (session, request_id)
            )
            row = db.execute(
                "SELECT revision FROM messages WHERE session_id=? AND request_id=?",
                (session, request_id),
            ).fetchone()
            result = {
                "text": "已停止這次操作。已送出的模型請求可能仍計費；已提交的預約須另行確認取消。",
                "interrupted": True,
            }
            if row and row["revision"] == who["revision"]:
                db.execute("UPDATE sessions SET revision=revision+1 WHERE id=?", (session,))
                db.execute(
                    "UPDATE operations SET status='cancelled',reason=?,updated=? WHERE session_id=? AND status IN ('draft','waiting_confirmation','executing')",
                    ("使用者中斷", self.clock(), session),
                )
                db.execute(
                    "UPDATE messages SET response=? WHERE session_id=? AND request_id=? AND response IS NULL",
                    (json.dumps(result, ensure_ascii=False), session, request_id),
                )
                self._event(
                    db, session, None, "cancelled", "使用者中斷模型處理；過期結果不得提交。"
                )
            return result

    def finish_turn(self, session, request_id, response):
        with self.db.connect(write=True) as db:
            who = self._session(db, session)
            row = db.execute(
                "SELECT revision,response FROM messages WHERE session_id=? AND request_id=?",
                (session, request_id),
            ).fetchone()
            if row is None:
                raise Conflict("訊息不存在。")
            if row["response"]:
                return json.loads(row["response"])
            if row["revision"] != who["revision"]:
                response = {"text": "這則回覆已被較新的訊息取代。", "superseded": True}
            elif response.get("response_kind") == "model_text":
                committed = db.execute(
                    "SELECT id FROM operations WHERE session_id=? AND revision=? AND status='committed'",
                    (session, row["revision"]),
                ).fetchall()
                response["verification"] = {
                    "status": "committed" if committed else "no_submission",
                    "text": "資料庫查證：本輪已有提交收據，請查看操作結果。"
                    if committed
                    else "資料庫查證：這則回覆沒有提交任何預約變更。",
                    "operation_ids": [op["id"] for op in committed],
                }
            db.execute(
                "UPDATE messages SET response=? WHERE session_id=? AND request_id=?",
                (json.dumps(response, ensure_ascii=False), session, request_id),
            )
            return response

    def _booking(self, db, owner, booking_id):
        row = db.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
        if row is None or row["owner"] != owner:
            raise Forbidden("無法存取這筆預約。")
        if row["status"] != "active":
            raise Conflict("預約已取消，請重新查詢。")
        return dict(row)

    def _slot(self, slot):
        try:
            parsed = datetime.fromisoformat(slot)
        except (ValueError, TypeError):
            raise SlotValidationError("invalid_slot", "slot", "請指定完整日期與時段。") from None
        if parsed.tzinfo is None:
            raise SlotValidationError("invalid_slot", "slot", "預約時間必須包含時區。")
        parsed = parsed.astimezone(TAIPEI)
        if parsed.hour not in (10, 14, 16) or parsed.minute or parsed.second or parsed.microsecond:
            raise SlotValidationError(
                "unsupported_time", "time", "可預約時段為 10:00、14:00、16:00。"
            )
        if parsed.timestamp() <= self.clock():
            raise SlotValidationError("past_slot", "date", "預約時段必須在未來。")
        return parsed.isoformat()

    def repair_slot_draft(self, session, revision, raw, error):
        """New incomplete draft only; never revive an old confirmation or bypass policy."""
        payload = Proposal.model_validate(raw).model_dump()
        if error.code not in ("unsupported_time", "past_slot") or payload["action"] not in (
            "create",
            "reschedule",
        ):
            return None
        if payload["slot"]:
            parsed = datetime.fromisoformat(payload["slot"])
            if parsed.tzinfo is None:
                return None
            parsed = parsed.astimezone(TAIPEI)
            if (payload["date"] and payload["date"] != parsed.date().isoformat()) or (
                payload["time"] and payload["time"] != parsed.strftime("%H:%M")
            ):
                return None
            payload["date"] = parsed.date().isoformat()
        payload["slot"] = payload["time"] = None
        today = datetime.fromtimestamp(self.clock(), TAIPEI).date()
        if error.code == "past_slot" or (
            payload["date"] and date.fromisoformat(payload["date"]) < today
        ):
            payload["date"] = None
        return self.propose(session, revision, payload)

    def propose(self, session, revision, raw, *, observed_versions=None):
        try:
            proposal = Proposal.model_validate(raw)
        except ValidationError:
            raise ValueError("操作欄位格式無效，請只提供支援的維修項目與預約資料。") from None
        payload = proposal.model_dump()
        if payload["date"]:
            try:
                date.fromisoformat(payload["date"])
            except ValueError:
                raise SlotValidationError("invalid_slot", "date", "請指定有效日期。") from None
        if payload["time"] and payload["time"] not in ("10:00", "14:00", "16:00"):
            raise SlotValidationError(
                "unsupported_time", "time", "可預約時段為 10:00、14:00、16:00。"
            )
        if payload["date"] and payload["time"] and not payload["slot"]:
            payload["slot"] = f"{payload['date']}T{payload['time']}:00+08:00"
        with self.db.connect(write=True) as db:
            who = self._session(db, session)
            if revision != who["revision"]:
                raise Conflict("提議已過期，請使用最新操作。")
            existing = db.execute(
                "SELECT * FROM operations WHERE session_id=? AND revision=?", (session, revision)
            ).fetchone()
            if existing:
                raise Conflict("此訊息已經有操作提議。")
            expected = None
            if proposal.action != "create" and proposal.booking_id:
                booking = self._booking(db, who["owner"], proposal.booking_id)
                if (
                    observed_versions is not None
                    and observed_versions.get(booking["id"]) != booking["version"]
                ):
                    raise Conflict("預約資訊尚未查詢或已變更，請重新查詢後提出操作。")
                expected = booking["version"]
                payload["service"] = booking["service"]
                if proposal.action == "cancel":
                    payload["slot"] = booking["slot"]
            if payload["slot"] and proposal.action != "cancel":
                payload["slot"] = self._slot(payload["slot"])
                if (payload["date"] and payload["date"] != payload["slot"][:10]) or (
                    payload["time"] and payload["time"] != payload["slot"][11:16]
                ):
                    raise ValueError("日期與時段欄位互相矛盾，請重新指定一致的預約時間。")
                payload["date"], payload["time"] = payload["slot"][:10], payload["slot"][11:16]
            if proposal.action == "create" and proposal.booking_id:
                raise ValueError("新預約不能指定既有預約編號。")
            complete = (
                bool(payload["service"] and payload["slot"])
                if proposal.action == "create"
                else bool(expected and (payload["slot"] or proposal.action == "cancel"))
            )
            op_id = uid()
            now = self.clock()
            db.execute(
                """INSERT INTO operations(id,session_id,owner,revision,action,payload,expected_version,
                       status,confirmation,expires,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    op_id,
                    session,
                    who["owner"],
                    revision,
                    proposal.action,
                    json.dumps(payload, ensure_ascii=False),
                    expected,
                    "draft",
                    secrets.token_urlsafe(32),
                    now + 300,
                    now,
                    now,
                ),
            )
            self._event(db, session, op_id, "draft", "已建立操作草案，尚未修改預約。")
            if complete:
                db.execute(
                    "UPDATE operations SET status='waiting_confirmation' WHERE id=?", (op_id,)
                )
                self._event(
                    db,
                    session,
                    op_id,
                    "waiting_confirmation",
                    "請確認操作內容；確認有效時間為 5 分鐘。",
                )
            return self._operation(db, session, op_id)

    def confirm(self, session, op_id, confirmation, fault="none"):
        if fault not in ("none", "before_commit", "after_commit"):
            raise ValueError("未知的示範故障。")
        with self.db.connect(write=True) as db:
            op = self._operation(db, session, op_id)
            if not secrets.compare_digest(op["confirmation"], confirmation):
                raise Forbidden("確認憑證不符。")
            if op["status"] == "committed":
                return {**op, "delivery": "verified"}
            if op["status"] not in ("waiting_confirmation", "executing"):
                raise Conflict("此操作無法確認，請查看最新操作。")
            who = self._session(db, session)
            if op["revision"] != who["revision"] or op["expires"] <= self.clock():
                raise Conflict("確認已過期，請重新提出操作。")
            if op["status"] == "waiting_confirmation":
                db.execute(
                    "UPDATE operations SET status='executing',confirmed=?,updated=? WHERE id=?",
                    (self.clock(), self.clock(), op_id),
                )
                self._event(db, session, op_id, "executing", "使用者已確認，準備執行交易。")
        if fault == "before_commit":
            with self.db.connect(write=True) as db:
                self._event(db, session, op_id, "unknown", "示範：提交前連線逾時。尚未查證結果。")
            return {"id": op_id, "status": "executing", "delivery": "unknown", "receipt": None}
        result = self._execute(session, op_id)
        if fault == "after_commit":
            with self.db.connect(write=True) as db:
                self._event(
                    db, session, op_id, "unknown", "示範：提交後回覆遺失。請以操作編號查證。"
                )
            return {"id": op_id, "status": "executing", "delivery": "unknown", "receipt": None}
        return {**result, "delivery": "verified"}

    def _execute(self, session, op_id):
        with self.db.connect(write=True) as db:
            op = self._operation(db, session, op_id)
            if op["status"] != "executing":
                return op
            who = self._session(db, session)
            if op["revision"] != who["revision"] or op["expires"] <= self.clock():
                db.execute(
                    "UPDATE operations SET status='cancelled',reason=?,updated=? WHERE id=?",
                    ("意圖或確認已過期", self.clock(), op_id),
                )
                self._event(db, session, op_id, "cancelled", "恢復檢查：授權已過期，未修改預約。")
                return self._operation(db, session, op_id)
            if op["confirmed"] is None:
                raise Forbidden("缺少使用者確認。")
            payload = op["payload"]
            db.execute("SAVEPOINT business")
            try:
                if op["action"] == "create":
                    booking_id = uid()
                    slot = self._slot(payload["slot"])
                    db.execute(
                        "INSERT INTO bookings VALUES(?,?,?,?, 'active',1)",
                        (booking_id, who["owner"], payload["service"], slot),
                    )
                else:
                    booking_id = payload["booking_id"]
                    booking = self._booking(db, who["owner"], booking_id)
                    if booking["version"] != op["expected_version"]:
                        raise Conflict("預約已被另一筆操作修改，請重新查詢及確認。")
                    if op["action"] == "reschedule":
                        db.execute(
                            "UPDATE bookings SET slot=?,version=version+1 WHERE id=?",
                            (self._slot(payload["slot"]), booking_id),
                        )
                    else:
                        db.execute(
                            "UPDATE bookings SET status='cancelled',version=version+1 WHERE id=?",
                            (booking_id,),
                        )
                booking = dict(
                    db.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
                )
                receipt = {"operation_id": op_id, "booking": booking, "committed_at": self.clock()}
                db.execute(
                    "UPDATE operations SET status='committed',receipt=?,updated=? WHERE id=?",
                    (json.dumps(receipt, ensure_ascii=False), self.clock(), op_id),
                )
                self._event(db, session, op_id, "committed", "預約變更與提交收據已共同保存。")
                db.execute("RELEASE business")
            except (Conflict, Forbidden, ValueError, sqlite3.IntegrityError) as exc:
                db.execute("ROLLBACK TO business")
                db.execute("RELEASE business")
                reason = (
                    "時段已被預約，請選擇其他時段。"
                    if isinstance(exc, sqlite3.IntegrityError)
                    else str(exc)
                )
                db.execute(
                    "UPDATE operations SET status='failed',reason=?,updated=? WHERE id=?",
                    (reason, self.clock(), op_id),
                )
                self._event(db, session, op_id, "failed", reason)
            return self._operation(db, session, op_id)

    def abandon(self, session, op_id):
        with self.db.connect(write=True) as db:
            op = self._operation(db, session, op_id)
            if op["status"] == "committed":
                raise Conflict("操作已提交；若要取消預約，請另外提出並確認取消操作。")
            if op["status"] in ("draft", "waiting_confirmation", "executing"):
                db.execute("UPDATE sessions SET revision=revision+1 WHERE id=?", (session,))
                db.execute(
                    "UPDATE operations SET status='cancelled',reason=?,updated=? WHERE id=?",
                    ("使用者取消尚未提交的操作", self.clock(), op_id),
                )
                self._event(db, session, op_id, "cancelled", "已取消尚未提交的操作。")
            return self._operation(db, session, op_id)

    def recover(self, session=None):
        with self.db.connect() as db:
            if session:
                self._session(db, session)
            rows = db.execute(
                "SELECT id,session_id FROM operations WHERE status='executing'"
                + (" AND session_id=?" if session else ""),
                (session,) if session else (),
            ).fetchall()
        return [self._execute(row["session_id"], row["id"]) for row in rows]

    def recover_interrupted_messages(self):
        """Run once at single-process startup; never race live model requests."""
        with self.db.connect(write=True) as db:
            rows = db.execute("SELECT id FROM messages WHERE response IS NULL").fetchall()
            for row in rows:
                response = {
                    "text": "處理訊息時程序中斷。已保存的操作請見確認單或結果區；尚缺的需求請重新提出。",
                    "interrupted": True,
                }
                db.execute(
                    "UPDATE messages SET response=? WHERE id=?",
                    (json.dumps(response, ensure_ascii=False), row["id"]),
                )

    def snapshot(self, session):
        with self.db.connect() as db:
            who = self._session(db, session)
            return {
                "identity": who["owner"],
                "csrf": who["csrf"],
                "revision": who["revision"],
                "bookings": [
                    dict(r)
                    for r in db.execute(
                        "SELECT * FROM bookings WHERE owner=? ORDER BY slot", (who["owner"],)
                    )
                ],
                "operations": [
                    self._decode(r)
                    for r in db.execute(
                        "SELECT * FROM operations WHERE session_id=? ORDER BY created DESC,rowid DESC",
                        (session,),
                    )
                ],
                "events": [
                    dict(r)
                    for r in db.execute(
                        "SELECT * FROM events WHERE session_id=? ORDER BY id DESC LIMIT 80",
                        (session,),
                    )
                ],
                "messages": [
                    {**dict(r), "response": json.loads(r["response"]) if r["response"] else None}
                    for r in db.execute(
                        "SELECT * FROM messages WHERE session_id=? ORDER BY id", (session,)
                    )
                ],
            }
