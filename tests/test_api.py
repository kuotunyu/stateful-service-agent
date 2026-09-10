from fastapi.testclient import TestClient

from agent.app import create_app


def client_for(tmp_path, owner="demo-alice"):
    client = TestClient(create_app(tmp_path / "api.db", demo_owner=owner))
    state = client.get("/api/state").json()
    client.headers["X-CSRF-Token"] = state["csrf"]
    return client


def send(client, text, request_id):
    response = client.post("/api/messages", json={"text": text, "request_id": request_id})
    assert response.status_code == 200, response.text
    return response.json()


def test_multiturn_mock_booking_and_reload_preserve_verified_state(tmp_path):
    client = client_for(tmp_path)
    first = send(client, "我要預約冷氣維修", "one")
    assert first["operation"]["status"] == "draft"
    second = send(client, "2030-01-08 10:00", "two")
    op = second["operation"]
    assert op["status"] == "waiting_confirmation"
    result = client.post(
        f"/api/operations/{op['id']}/confirm",
        json={"confirmation": op["confirmation"], "fault": "after_commit"},
    )
    assert result.status_code == 202
    state = client.post("/api/recover").json()
    assert [(b["owner"], b["status"]) for b in state["bookings"]] == [("demo-alice", "active")]
    assert client.get("/api/state").json()["bookings"] == state["bookings"]


def test_browser_cannot_supply_identity_or_forge_confirmation(tmp_path):
    client = client_for(tmp_path)
    assert (
        client.post(
            "/api/messages", json={"text": "預約", "request_id": "bad", "user_id": "bob"}
        ).status_code
        == 422
    )
    op = send(client, "預約冷氣維修 2030-01-08 10:00", "valid")["operation"]
    assert (
        client.post(
            f"/api/operations/{op['id']}/confirm", json={"confirmation": "model-says-approved"}
        ).status_code
        == 403
    )
    assert client.get("/api/state").json()["bookings"] == []


def test_csrf_and_cross_origin_requests_cannot_change_intent(tmp_path):
    client = client_for(tmp_path)
    body = {"text": "預約", "request_id": "bad"}
    assert (
        client.post(
            "/api/messages", json=body, headers={"Origin": "https://attacker.example"}
        ).status_code
        == 403
    )
    client.headers.pop("X-CSRF-Token")
    assert client.post("/api/messages", json=body).status_code == 403
    assert client.get("/api/state").json()["revision"] == 0


def test_replayed_user_request_does_not_invalidate_its_confirmation(tmp_path):
    client = client_for(tmp_path)
    first = send(client, "預約洗衣機維修 2030-01-08 14:00", "same")
    again = send(client, "預約洗衣機維修 2030-01-08 14:00", "same")
    assert first == again
    op = first["operation"]
    assert (
        client.post(
            f"/api/operations/{op['id']}/confirm", json={"confirmation": op["confirmation"]}
        ).json()["status"]
        == "committed"
    )


def test_user_reversal_and_query_never_create_a_booking(tmp_path):
    client = client_for(tmp_path)
    op = send(client, "預約冷氣維修 2030-01-08 10:00", "one")["operation"]
    send(client, "先不要", "two")
    assert (
        client.post(
            f"/api/operations/{op['id']}/confirm", json={"confirmation": op["confirmation"]}
        ).status_code
        == 409
    )
    send(client, "查詢我的預約", "three")
    assert client.get("/api/state").json()["bookings"] == []


def test_structured_booking_controls_follow_same_confirmation_boundary(tmp_path):
    client = client_for(tmp_path)
    response = client.post(
        "/api/proposals",
        json={
            "request_id": "form",
            "proposal": {
                "action": "create",
                "service": "冷氣維修",
                "slot": "2030-01-08T10:00:00+08:00",
            },
        },
    )
    assert response.status_code == 200
    assert response.json()["operation"]["status"] == "waiting_confirmation"
    assert client.get("/api/state").json()["bookings"] == []
