import threading
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi.testclient import TestClient

from agent.app import create_app
from agent.orchestration import ModelConfig, ReplayModel


def test_live_proposal_replay_and_confirmation(tmp_path):
    model = ReplayModel(
        [
            {
                "tool": "propose",
                "arguments": {
                    "action": "create",
                    "service": "冷氣維修",
                    "slot": "2030-01-08T10:00:00+08:00",
                },
            }
        ]
    )
    with TestClient(create_app(tmp_path / "app.db", model=model)) as client:
        state = client.get("/api/state").json()
        headers = {"X-CSRF-Token": state["csrf"]}
        body = {"request_id": "one", "text": "預約", "mode": "fixed"}
        result = client.post("/api/messages", json=body, headers=headers).json()
        assert result["mode"] == "fixed"
        assert client.get("/api/state").json()["bookings"] == []
        assert client.post("/api/messages", json=body, headers=headers).json() == result
        op = result["operation"]
        assert (
            client.post(
                f"/api/operations/{op['id']}/confirm",
                json={"confirmation": op["confirmation"]},
                headers=headers,
            ).status_code
            == 200
        )
        assert len(client.get("/api/state").json()["bookings"]) == 1


def test_interrupt_blocks_late_model_and_further_agent_calls(tmp_path):
    entered, release = threading.Event(), threading.Event()
    calls = []

    class SlowModel:
        def respond(self, messages, config):
            calls.append(messages)
            entered.set()
            assert release.wait(5)
            return {"tool": "read_context", "arguments": {}}

    with TestClient(create_app(tmp_path / "app.db", model=SlowModel())) as client:
        state = client.get("/api/state").json()
        headers = {"X-CSRF-Token": state["csrf"]}
        with ThreadPoolExecutor() as pool:
            pending = pool.submit(
                client.post,
                "/api/messages",
                json={"request_id": "slow", "text": "預約", "mode": "agent"},
                headers=headers,
            )
            assert entered.wait(5)
            try:
                assert (
                    client.post(
                        "/api/messages/slow/interrupt", json={}, headers=headers
                    ).status_code
                    == 200
                )
            finally:
                release.set()
            assert pending.result().json()["interrupted"] is True
        assert len(calls) == 1
        assert client.get("/api/state").json()["operations"] == []


def test_interrupt_arrives_before_message_and_model_error_is_durable(tmp_path):
    class BrokenModel:
        def respond(self, messages, config):
            raise RuntimeError("sensitive transport details must not reach the UI")

    with TestClient(create_app(tmp_path / "app.db", model=BrokenModel())) as client:
        state = client.get("/api/state").json()
        headers = {"X-CSRF-Token": state["csrf"]}
        assert (
            client.post("/api/messages/late/interrupt", json={}, headers=headers).status_code == 200
        )
        body = {"request_id": "late", "text": "預約", "mode": "fixed"}
        assert client.post("/api/messages", json=body, headers=headers).status_code == 409
        body["request_id"] = "error"
        result = client.post("/api/messages", json=body, headers=headers).json()
        assert result["rejected"] is True
        assert "sensitive" not in str(result)
        assert client.post("/api/messages", json=body, headers=headers).json() == result


def test_persistent_budget_serializes_reservations_and_survives_restart(tmp_path):
    from agent.live_model import LiveModel

    def transport(request):
        raise httpx.ReadTimeout("unknown")

    kwargs = {
        "api_key": "fake",
        "authorized": True,
        "max_requests": 1,
        "baseline": None,
        "transport": httpx.MockTransport(transport),
    }
    model = LiveModel(tmp_path / "usage", **kwargs)

    def call():
        with pytest.raises(RuntimeError):
            model.respond([], ModelConfig())

    with ThreadPoolExecutor() as pool:
        list(pool.map(lambda _: call(), range(2)))
    usage = LiveModel(tmp_path / "usage", **kwargs).status()
    assert usage["requests"] == 1
    assert usage["reserved_usd"] > 0
    assert usage["unknown_requests"] == 1
    assert usage["actual_usd"] == 0


def test_budget_imports_prior_pilot_exactly_once(tmp_path):
    from pathlib import Path

    from agent.live_model import LiveModel

    kwargs = {
        "api_key": "fake",
        "authorized": True,
        "baseline": Path("docs/evaluations/paid-pilot-01/usage-ledger.jsonl"),
    }
    first = LiveModel(tmp_path / "usage", **kwargs).status()
    second = LiveModel(tmp_path / "usage", **kwargs).status()
    assert first == second
    assert first["requests"] == 33
    assert first["actual_usd"] == pytest.approx(0.0100752)
    assert first["reserved_usd"] == pytest.approx(0.0897152)
