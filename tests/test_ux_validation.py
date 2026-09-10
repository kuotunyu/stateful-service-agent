import pytest
from test_api import client_for, send

from agent import mock
from agent.service import BookingService, Conflict


def confirm(client, op):
    return client.post(
        f"/api/operations/{op['id']}/confirm", json={"confirmation": op["confirmation"]}
    )


def test_invalid_time_creates_new_draft_and_can_continue(tmp_path):
    client = client_for(tmp_path)
    old = send(client, "預約冷氣維修 2030-01-08 10:00", "initial")["operation"]
    rejected = send(client, "改成 2030-01-08 15:00", "invalid")
    assert rejected["rejected"]
    assert rejected["validation"] == {"code": "unsupported_time", "field": "time"}
    draft = rejected["operation"]
    assert draft["id"] != old["id"] and draft["status"] == "draft"
    assert draft["payload"]["slot"] is None and draft["payload"]["time"] is None
    assert confirm(client, old).status_code == 409
    assert send(client, "改成 2030-01-08 15:00", "invalid") == rejected
    updated = send(client, "那就 2030-01-08 16:00", "corrected")["operation"]
    assert updated["status"] == "waiting_confirmation"
    assert updated["payload"]["slot"] == "2030-01-08T16:00:00+08:00"
    assert client.get("/api/state").json()["bookings"] == []


def test_reschedule_error_keeps_selected_booking_and_abandon_cannot_revive(tmp_path):
    client = client_for(tmp_path)
    bookings = []
    for i, day in enumerate((8, 9)):
        op = send(client, f"預約冷氣維修 2030-01-{day:02} 10:00", f"create-{i}")["operation"]
        bookings.append(confirm(client, op).json()["receipt"]["booking"])
    selected = bookings[1]["id"]
    send(client, f"改期 {selected}", "select")
    rejected = send(client, "明天 15:00", "bad")
    assert rejected["operation"]["payload"]["booking_id"] == selected
    assert rejected["operation"]["status"] == "draft"
    fixed = send(client, "那就 2030-01-10 16:00", "fix")["operation"]
    assert fixed["payload"]["booking_id"] == selected
    send(client, "2030-01-10 15:00", "bad-again")
    send(client, "先不要", "abandon")
    assert "operation" not in send(client, "16:00", "orphan")
    assert client.get("/api/state").json()["bookings"] == bookings


def test_past_date_draft_clears_all_time_fields_and_form_reports_field(tmp_path):
    client = client_for(tmp_path)
    result = send(client, "預約冷氣維修 2000-01-01 14:00", "past")
    assert result["validation"] == {"code": "past_slot", "field": "date"}
    assert all(result["operation"]["payload"][key] is None for key in ("slot", "date", "time"))
    response = client.post(
        "/api/proposals",
        json={
            "request_id": "form",
            "proposal": {
                "action": "create",
                "service": "冷氣維修",
                "slot": "2000-01-01T14:00:00+08:00",
            },
        },
    ).json()
    assert response["validation"]["field"] == "date" and "operation" not in response


def test_invalid_time_cannot_sanitize_away_forbidden_identity(tmp_path, monkeypatch):
    client = client_for(tmp_path)
    monkeypatch.setattr(
        mock,
        "parse",
        lambda *args: {
            "kind": "proposal",
            "proposal": {
                "action": "reschedule",
                "booking_id": "foreign",
                "time": "15:00",
                "user_id": "bob",
            },
        },
    )
    result = send(client, "repair", "bad")
    assert result["rejected"] and "operation" not in result
    assert client.get("/api/state").json()["operations"] == []


@pytest.mark.parametrize("unsupported", ["下週一 14:00", "週末下午兩點"])
def test_unsupported_date_does_not_reuse_old_date(tmp_path, unsupported):
    client = client_for(tmp_path)
    send(client, "預約冷氣維修 2030-01-08 10:00", "initial")
    result = send(client, unsupported, "unsupported")
    assert "operation" not in result
    assert result["show_form"] is True and "YYYY-MM-DD" in result["text"]


def test_typed_query_discloses_pending_operation_replacement(tmp_path):
    client = client_for(tmp_path)
    old = send(client, "預約冷氣維修 2030-01-08 10:00", "old")["operation"]
    result = send(client, "查詢預約", "query")
    assert "先前待確認內容已被這則新訊息取代" in result["text"]
    assert confirm(client, old).status_code == 409


def test_confirmation_at_exact_expiry_is_rejected_without_write(tmp_path):
    now = [1893456000.0]
    svc = BookingService(tmp_path / "expiry.db", clock=lambda: now[0])
    session = svc.new_session("alice")["id"]
    turn = svc.begin_turn(session, "create", "create")
    op = svc.propose(
        session,
        turn["revision"],
        {
            "action": "create",
            "service": "冷氣維修",
            "slot": "2030-01-08T10:00:00+08:00",
        },
    )
    now[0] = op["expires"]
    with pytest.raises(Conflict):
        svc.confirm(session, op["id"], op["confirmation"])
    assert svc.snapshot(session)["bookings"] == []
