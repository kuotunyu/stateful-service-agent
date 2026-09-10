"""Local launcher. Reuse matching services; never terminate an occupied port."""

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent


def instance_id():
    return hashlib.sha256(str(ROOT).casefold().encode()).hexdigest()[:16]


def probe(port):
    try:
        response = httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=1, trust_env=False)
        if response.status_code == 200:
            body = response.json()
            return body if isinstance(body, dict) else {"app": "unknown"}
        return {"app": "unknown"}
    except (httpx.HTTPError, ValueError):
        # A non-HTTP service may occupy the port too. Do not spawn over it.
        with socket.socket() as connection:
            connection.settimeout(0.3)
            return {"app": "unknown"} if connection.connect_ex(("127.0.0.1", port)) == 0 else None


def matches(state, live):
    return (
        state.get("app") == "stateful-service-agent"
        and state.get("instance") == instance_id()
        and state.get("database") == "ok"
        and (not live or state.get("model_available"))
    )


def spawn(port, live):
    factory = "create_live_app" if live else "create_app"
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        f"agent.app:{factory}",
        "--factory",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]
    if live:
        uv = shutil.which("uv")
        if not uv or not (ROOT / ".env").is_file():
            raise RuntimeError("Live mode requires uv and this project's .env. See README.md.")
        # uv expands env-file globs; Windows backslashes are escape characters.
        command = [uv, "run", "--locked", "--env-file", (ROOT / ".env").as_posix(), *command]
    logs = ROOT / "data"
    logs.mkdir(exist_ok=True)
    env = {**os.environ, "STATEFUL_ENABLE_MODEL": "0"}
    for name in ("STATEFUL_OPENAI_API_KEY", "UV_ENV_FILE", "UV_NO_ENV_FILE"):
        env.pop(name, None)
    with (logs / f"launcher-{port}.log").open("ab") as output:
        return subprocess.Popen(
            command,
            cwd=ROOT,
            env=env,
            stdout=output,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            start_new_session=os.name != "nt",
        )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Load only this project's .env; UI still defaults to mock",
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--status", action="store_true", help="Check only; never launch")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    if not 1024 <= args.port <= 65535:
        parser.error("Use a port from 1024 through 65535")
    state = probe(args.port)
    url = f"http://127.0.0.1:{args.port}"
    if args.status:
        status = (
            state
            if state and matches(state, args.live)
            else {
                "status": "not running"
                if state is None
                else "occupied by a different service or mode"
            }
        )
        print(json.dumps(status))
        return 0 if state and matches(state, args.live) else 1
    if state is not None:
        if not matches(state, args.live):
            print(
                "Port occupied by a different service or mode. Choose --port; no process was stopped."
            )
            return 2
        print(f"Workspace already running: {url}")
    else:
        try:
            process = spawn(args.port, args.live)
        except (OSError, RuntimeError) as exc:
            print(str(exc))
            return 2
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            state = probe(args.port)
            if state and matches(state, args.live):
                print(f"Workspace ready: {url} (server PID {state['pid']})")
                break
            if process.poll() is not None:
                break
            time.sleep(0.2)
        if not state or not matches(state, args.live):
            print(
                f"Startup not confirmed. Check data/launcher-{args.port}.log; no existing process was stopped."
            )
            return 2
    if not args.no_browser:
        webbrowser.open(url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
