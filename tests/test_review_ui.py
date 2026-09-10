from fastapi.testclient import TestClient

from agent.app import create_app
from agent.launch import database_fingerprint, matches


def test_unknown_legacy_session_cookie_recovers_to_demo_owner(tmp_path):
    with TestClient(create_app(tmp_path / "one.db")) as client:
        client.cookies.set("repair_session", "missing-session")
        response = client.get("/api/state")
        assert response.status_code == 200
        assert response.json()["identity"] == "demo-alice"
        assert response.cookies.get("repair_session") != "missing-session"


def test_database_specific_cookie_preserves_legacy_session(tmp_path):
    path = tmp_path / "one.db"
    app = create_app(path)
    legacy = app.state.service.new_session("legacy-owner")
    with TestClient(app) as client:
        client.cookies.set("repair_session", legacy["id"])
        response = client.get("/api/state")
        assert response.json()["identity"] == "legacy-owner"
        cookie_name = f"repair_session_{database_fingerprint(path)}"
        assert response.cookies.get(cookie_name) == legacy["id"]


def test_stale_database_cookie_falls_back_to_valid_legacy_session(tmp_path):
    path = tmp_path / "one.db"
    app = create_app(path)
    legacy = app.state.service.new_session("legacy-owner")
    with TestClient(app) as client:
        client.cookies.set(f"repair_session_{database_fingerprint(path)}", "stale")
        client.cookies.set("repair_session", legacy["id"])
        response = client.get("/api/state")
        assert response.json()["identity"] == "legacy-owner"


def test_database_cookie_from_another_database_is_not_reused(tmp_path):
    first_path = tmp_path / "first.db"
    second_path = tmp_path / "second.db"
    first = create_app(first_path)
    first_session = first.state.service.new_session("first-owner")
    with TestClient(create_app(second_path)) as client:
        client.cookies.set(
            f"repair_session_{database_fingerprint(first_path)}", first_session["id"]
        )
        response = client.get("/api/state")
        assert response.json()["identity"] == "demo-alice"
        assert response.cookies.get(f"repair_session_{database_fingerprint(second_path)}")


def test_health_and_launcher_match_database_fingerprint_without_path(tmp_path):
    path = tmp_path / "private" / "bookings.db"
    with TestClient(create_app(path)) as client:
        health = client.get("/api/health").json()
    assert health["database"] == "ok"
    assert health["database_fingerprint"] == database_fingerprint(path)
    assert str(path) not in str(health)
    assert matches(health, live=False, database=path)
    assert not matches(health, live=False, database=tmp_path / "other.db")


def test_launcher_resolves_relative_database_from_spawn_root(tmp_path, monkeypatch):
    from agent import launch

    root = tmp_path / "project"
    root.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setattr(launch, "ROOT", root)
    monkeypatch.setenv("STATEFUL_DB", "data/custom.db")
    monkeypatch.chdir(elsewhere)
    assert launch.database_fingerprint() == launch.database_fingerprint(root / "data" / "custom.db")
