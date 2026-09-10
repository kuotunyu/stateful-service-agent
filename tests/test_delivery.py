import pytest
from fastapi.testclient import TestClient

from agent.app import create_app


def test_health_does_not_create_session_or_read_credentials(tmp_path):
    app = create_app(tmp_path / "health.db")
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["app"] == "stateful-service-agent"
        assert health.json()["database"] == "ok"
        assert not health.json()["model_available"]
        assert not health.cookies
        with app.state.service.db.connect() as db:
            assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0


def test_evidence_page_uses_fixed_public_artifacts(tmp_path):
    with TestClient(create_app(tmp_path / "evidence.db")) as client:
        assert client.get("/evaluation").status_code == 200
        evidence = client.get("/api/evaluation").json()
        assert evidence["summary"]["strategies"]["fixed"]["task_success_rate"] == 0.875
        failures = [case for case in evidence["cases"] if not case["task_success"]]
        assert len(failures) == 1
        assert failures[0]["case"] == "spoofed_owner_authorization"
        assert client.get("/api/evaluation/.env").status_code == 404
        assert client.get("/api/evaluation/files/.env").status_code == 404
        artifact = client.get("/api/evaluation/files/summary.json")
        assert artifact.status_code == 200
        assert "attachment" in artifact.headers["content-disposition"]


def test_launcher_reuses_matching_service_and_rejects_unrelated_port(monkeypatch, capsys):
    from agent import launch

    monkeypatch.setattr(
        launch,
        "probe",
        lambda port: {
            "app": "stateful-service-agent",
            "instance": launch.instance_id(),
            "database": "ok",
            "model_available": False,
        },
    )
    monkeypatch.setattr(
        launch, "spawn", lambda *args: (_ for _ in ()).throw(AssertionError("must not spawn"))
    )
    assert launch.main(["--no-browser"]) == 0
    assert "already running" in capsys.readouterr().out
    assert launch.main(["--live", "--no-browser"]) == 2
    monkeypatch.setattr(launch, "probe", lambda port: {"app": "another-project"})
    assert launch.main(["--no-browser"]) == 2


def test_launcher_status_never_starts_service(monkeypatch):
    from agent import launch

    monkeypatch.setattr(launch, "probe", lambda port: None)
    monkeypatch.setattr(
        launch, "spawn", lambda *args: (_ for _ in ()).throw(AssertionError("must not spawn"))
    )
    assert launch.main(["--status"]) == 1


def test_launcher_rejects_empty_health_object_without_spawning(monkeypatch):
    from agent import launch

    monkeypatch.setattr(launch, "probe", lambda port: {})
    monkeypatch.setattr(
        launch, "spawn", lambda *args: pytest.fail("Occupied port started a process")
    )
    assert launch.main(["--no-browser"]) == 2


def test_server_refuses_second_process_lifespan_before_recovering(tmp_path):
    path = tmp_path / "single.db"
    with (
        TestClient(create_app(path)),
        pytest.raises(RuntimeError, match="already served"),
        TestClient(create_app(path)),
    ):
        pytest.fail("Second server may recover a live request")
    with TestClient(create_app(path)) as client:
        assert client.get("/api/health").status_code == 200


def test_live_child_key_can_only_come_from_project_env(tmp_path, monkeypatch):
    from agent import launch

    monkeypatch.setattr(launch, "ROOT", tmp_path)
    (tmp_path / ".env").write_text("STATEFUL_OPENAI_API_KEY=fake-project-key")
    monkeypatch.setenv("STATEFUL_OPENAI_API_KEY", "fake-inherited-key")
    monkeypatch.setenv("UV_ENV_FILE", "do-not-read")
    monkeypatch.setattr(launch.shutil, "which", lambda name: "uv")
    calls = []
    monkeypatch.setattr(
        launch.subprocess, "Popen", lambda command, **kwargs: calls.append((command, kwargs))
    )
    launch.spawn(8877, True)
    command, kwargs = calls[0]
    assert kwargs["env"].get("STATEFUL_OPENAI_API_KEY") is None
    assert kwargs["env"].get("UV_ENV_FILE") is None
    assert (tmp_path / ".env").as_posix() in command


def test_launcher_starts_real_service_once_and_reports_health(tmp_path, monkeypatch):
    import socket

    from agent import launch

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    monkeypatch.setenv("STATEFUL_DB", str(tmp_path / "launcher.db"))
    processes = []
    original = launch.spawn

    def own_process(port, live):
        process = original(port, live)
        processes.append(process)
        return process

    monkeypatch.setattr(launch, "spawn", own_process)
    try:
        args = ["--no-browser", "--port", str(port)]
        assert launch.main(args) == 0
        assert launch.main(args) == 0
        assert len(processes) == 1
        assert launch.main(["--status", "--port", str(port)]) == 0
    finally:
        for process in processes:
            process.terminate()
            process.wait(timeout=5)
