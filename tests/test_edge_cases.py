import threading

from fastapi.testclient import TestClient
from test_api import client_for, send

from agent.app import create_app
from agent.service import BookingService


def test_date_and_time_can_be_supplied_in_separate_turns(tmp_path):
    client = client_for(tmp_path)
    send(client, "我要預約冷氣維修", "one")
    send(client, "2030-01-08", "two")
    result = send(client, "下午兩點", "three")
    assert result["operation"]["payload"]["slot"] == "2030-01-08T14:00:00+08:00"
    assert result["operation"]["status"] == "waiting_confirmation"


def test_restart_resolves_interrupted_message_without_implicitly_confirming(tmp_path):
    path = tmp_path / "interrupted.db"
    svc = BookingService(path)
    session = svc.new_session("alice")
    svc.begin_turn(session["id"], "interrupted", "預約冷氣維修")
    with TestClient(create_app(path)) as client:
        client.cookies.set("repair_session", session["id"])
        state = client.get("/api/state").json()
    assert state["messages"][0]["response"]["interrupted"] is True
    assert state["bookings"] == []


def test_snapshot_reads_use_one_database_version(tmp_path):
    svc = BookingService(tmp_path / "snapshot.db")
    session = svc.new_session("alice")["id"]
    with svc.db.connect() as db:
        assert db.execute("SELECT revision FROM sessions WHERE id=?", (session,)).fetchone()[0] == 0
        worker = threading.Thread(target=lambda: svc.begin_turn(session, "next", "查詢"))
        worker.start()
        worker.join(timeout=3)
        assert not worker.is_alive()
        # Removing the read transaction would let a single UI response mix revisions.
        assert db.execute("SELECT revision FROM sessions WHERE id=?", (session,)).fetchone()[0] == 0


def test_delayed_parser_cannot_replace_a_newer_user_intent(tmp_path, monkeypatch):
    from agent import mock

    client = client_for(tmp_path)
    entered, resume = threading.Event(), threading.Event()
    real_parse = mock.parse

    def delayed(text, *args):
        if text.startswith("預約"):
            entered.set()
            assert resume.wait(5)
        return real_parse(text, *args)

    monkeypatch.setattr(mock, "parse", delayed)
    results = []
    worker = threading.Thread(
        target=lambda: results.append(send(client, "預約冷氣維修 2030-01-08 10:00", "slow"))
    )
    worker.start()
    assert entered.wait(5)
    send(client, "先不要", "new")
    resume.set()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert results[0]["superseded"] is True
    state = client.get("/api/state").json()
    assert state["bookings"] == []
    assert not any(op["status"] == "waiting_confirmation" for op in state["operations"])


def test_reschedule_followup_keeps_explicitly_selected_booking():
    from agent.mock import parse

    previous = {
        "status": "draft",
        "payload": {
            "action": "reschedule",
            "booking_id": "selected",
            "service": "冷氣維修",
            "slot": None,
        },
    }
    bookings = [{"id": "selected", "status": "active"}, {"id": "another", "status": "active"}]
    decision = parse("改到 2030-01-09 14:00", previous, bookings, 1893456000)
    assert decision["proposal"]["booking_id"] == "selected"


def test_new_create_intent_does_not_inherit_pending_cancel_action():
    from agent.mock import parse

    previous = {
        "status": "waiting_confirmation",
        "payload": {
            "action": "cancel",
            "booking_id": "old",
            "service": "冷氣維修",
            "slot": "2030-01-08T10:00:00+08:00",
        },
    }
    result = parse("我要預約洗衣機維修 2030-01-09 14:00", previous, [], 1893456000)
    assert result["proposal"]["action"] == "create"
    assert not result["proposal"].get("booking_id")
