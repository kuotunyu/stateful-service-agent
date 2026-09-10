import json
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from agent import mock
from agent.models import Proposal
from agent.orchestration import ModelConfig, run_turn
from agent.service import BookingService, Conflict, Forbidden


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Message(Input):
    text: str = Field(min_length=1, max_length=2000)
    request_id: str = Field(min_length=1, max_length=100)
    mode: Literal["mock", "fixed", "agent"] = "mock"


class FormProposal(Input):
    request_id: str = Field(min_length=1, max_length=100)
    proposal: Proposal


class Confirmation(Input):
    confirmation: str = Field(min_length=1, max_length=100)
    fault: Literal["none", "before_commit", "after_commit"] = "none"


def create_app(database=None, demo_owner="demo-alice", model=None, enable_model=False):
    service = BookingService(database or os.environ.get("STATEFUL_DB", "data/bookings.db"))
    if model is None and (enable_model or os.environ.get("STATEFUL_ENABLE_MODEL") == "1"):
        from agent.live_model import LiveModel

        root = Path(__file__).resolve().parent.parent
        model = LiveModel(
            root / "data/model-usage",
            authorized=True,
            api_key=os.environ.get("STATEFUL_OPENAI_API_KEY"),
            baseline=root / "docs/evaluations/paid-pilot-01/usage-ledger.jsonl",
        )

    @asynccontextmanager
    async def lifespan(app):
        service.recover()
        service.recover_interrupted_messages()
        yield

    app = FastAPI(title="Stateful Service Agent", lifespan=lifespan)
    app.state.service = service
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"]
    )

    @app.exception_handler(Conflict)
    async def conflict(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(Forbidden)
    async def forbidden(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=403)

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.middleware("http")
    async def headers(request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    def authenticated(request: Request):
        session_id = request.cookies.get("repair_session", "")
        who = service.session(session_id)
        if request.method != "GET":
            origin = request.headers.get("origin")
            if origin and origin != f"{request.url.scheme}://{request.url.netloc}":
                raise Forbidden("拒絕跨來源修改。")
            if not secrets.compare_digest(request.headers.get("x-csrf-token", ""), who["csrf"]):
                raise Forbidden("工作階段驗證失敗，請重新整理頁面。")
        return session_id

    Session = Annotated[str, Depends(authenticated)]

    @app.get("/api/state")
    def state(request: Request, response: Response):
        session_id = request.cookies.get("repair_session")
        if not session_id:
            session_id = service.new_session(demo_owner)["id"]
            response.set_cookie(
                "repair_session", session_id, httponly=True, samesite="strict", max_age=86400
            )
        result = service.snapshot(session_id)
        result["mode"] = "mock"
        result["model_available"] = model is not None
        result["model_usage"] = model.status() if hasattr(model, "status") else None
        return result

    def replay(turn):
        if turn["response"]:
            return json.loads(turn["response"])
        raise HTTPException(409, "同一請求仍在處理；請查詢目前狀態，不要建立新的請求。")

    @app.post("/api/messages")
    def message(body: Message, session: Session):
        if body.mode != "mock":
            if model is None:
                raise HTTPException(409, "真實模型尚未啟用，請使用 mock 或表單。")
            return run_turn(
                service,
                session,
                body.request_id,
                body.text,
                body.mode,
                model,
                ModelConfig(),
                live=True,
            )
        turn = service.begin_turn(session, body.request_id, body.text)
        if turn["replayed"]:
            return replay(turn)
        snapshot = service.snapshot(session)
        decision = mock.parse(
            body.text, turn.get("previous"), snapshot["bookings"], service.clock()
        )
        try:
            if decision["kind"] == "proposal":
                op = service.propose(session, turn["revision"], decision["proposal"])
                result = {"text": mock.describe(op), "operation": op}
            elif decision["kind"] == "abandon":
                result = {
                    "text": "已放棄尚未提交的操作。已提交的預約仍會保留；如需取消，請另行提出並確認。"
                }
            elif decision["kind"] == "query":
                count = len([b for b in snapshot["bookings"] if b["status"] == "active"])
                result = {"text": f"你目前有 {count} 筆有效預約，詳細內容顯示在預約區。"}
            else:
                result = {
                    "text": "這是 mock 示範，可輸入「預約冷氣維修，明天 10:00」、查詢、改期或取消。也可使用預約表單。"
                }
        except (ValueError, Conflict, Forbidden) as exc:
            result = {"text": str(exc), "rejected": True}
        return service.finish_turn(session, body.request_id, result)

    @app.post("/api/messages/{request_id}/interrupt")
    def interrupt(request_id: str, session: Session):
        if not 1 <= len(request_id) <= 100:
            raise ValueError("Invalid request ID")
        return service.interrupt_turn(session, request_id)

    @app.post("/api/proposals")
    def proposal(body: FormProposal, session: Session):
        raw = body.proposal.model_dump()
        description = json.dumps(raw, ensure_ascii=False, sort_keys=True)
        turn = service.begin_turn(session, body.request_id, description)
        if turn["replayed"]:
            return replay(turn)
        try:
            op = service.propose(session, turn["revision"], raw)
            result = {"text": mock.describe(op), "operation": op}
        except (ValueError, Conflict, Forbidden) as exc:
            result = {"text": str(exc), "rejected": True}
        result["mode"] = "form"
        return service.finish_turn(session, body.request_id, result)

    @app.post("/api/operations/{op_id}/confirm")
    def confirm(op_id: str, body: Confirmation, session: Session):
        result = service.confirm(session, op_id, body.confirmation, fault=body.fault)
        return JSONResponse(result, status_code=202 if result["delivery"] == "unknown" else 200)

    @app.post("/api/operations/{op_id}/abandon")
    def abandon(op_id: str, session: Session):
        return service.abandon(session, op_id)

    @app.post("/api/recover")
    def recover(session: Session):
        service.recover(session)
        return service.snapshot(session)

    static = Path(__file__).parent / "static"
    static.mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory=static), name="static")

    @app.get("/")
    def index():
        return FileResponse(static / "index.html")

    return app


def create_live_app():
    """Explicit opt-in factory; the launch command loads this project's .env."""
    return create_app(enable_model=True)
