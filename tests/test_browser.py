"""Real browser + real HTTP + independent SQLite assertions. CPU only."""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import expect, sync_playwright

from agent.service import BookingService


@pytest.fixture
def live_server(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {**os.environ, "STATEFUL_DB": str(tmp_path / "browser.db"), "STATEFUL_ENABLE_MODEL": "0"}
    process = None
    url = f"http://127.0.0.1:{port}"

    def start():
        nonlocal process
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "agent.app:create_app",
                "--factory",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            assert process.poll() is None, "own test server failed to start"
            try:
                if httpx.get(url, timeout=0.5).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.03)
        raise AssertionError("server did not start")

    def stop():
        if process and process.poll() is None:
            process.kill()
            process.wait(timeout=5)

    start()
    try:
        yield {"url": url, "path": env["STATEFUL_DB"], "restart": lambda: (stop(), start())}
    finally:
        stop()


def send(page, text):
    page.locator("#message").fill(text)
    with page.expect_response("**/api/messages"):
        page.locator("#send").click()
    expect(page.locator("#send")).to_be_enabled()


def db_bookings(server):
    service = BookingService(server["path"])
    with service.db.connect() as db:
        return [dict(r) for r in db.execute("SELECT * FROM bookings ORDER BY slot")]


def test_evidence_browser_filters_failure_and_preserves_mobile_layout(live_server):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(live_server["url"] + "/evaluation")
        expect(page.locator("#case-list > details")).to_have_count(16)
        expect(page.locator("#comparison")).to_contain_text("7/8")
        Path("artifacts").mkdir(exist_ok=True)
        page.screenshot(path="artifacts/evaluation-desktop.png", full_page=True)
        page.locator("#case-filter").select_option("failed")
        expect(page.locator("#case-list > details")).to_have_count(1)
        page.locator("#case-list > details > summary").click()
        expect(page.locator(".case-body")).to_contain_text("other-842")
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path="artifacts/evaluation-mobile.png", full_page=True)
        assert not errors
        browser.close()


def test_browser_crud_reversal_timeout_and_real_restart(live_server):
    artifacts = Path("artifacts")
    artifacts.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(live_server["url"])
        page.wait_for_load_state("networkidle")
        send(page, "預約冷氣維修 2030-01-08 10:00")
        expect(page.get_by_role("button", name="確認建立預約", exact=True)).to_be_visible()
        assert db_bookings(live_server) == []
        page.screenshot(path=str(artifacts / "desktop-confirmation.png"), full_page=True)
        page.get_by_role("button", name="確認建立預約", exact=True).click()
        expect(page.locator("#booking-count")).to_have_text("1")
        assert db_bookings(live_server)[0]["version"] == 1

        page.get_by_role("button", name="改期", exact=True).click()
        expect(page.locator("#confirmation")).to_contain_text("操作草案")
        send(page, "2030-01-09 14:00")
        page.get_by_role("button", name="確認改期預約", exact=True).click()
        expect(page.locator(".booking .when")).to_contain_text("14:00")
        assert db_bookings(live_server)[0]["slot"] == "2030-01-09T14:00:00+08:00"
        page.get_by_role("button", name="取消預約", exact=True).click()
        page.get_by_role("button", name="確認取消預約", exact=True).click()
        expect(page.locator("#booking-count")).to_have_text("0")
        assert db_bookings(live_server)[0]["status"] == "cancelled"

        send(page, "預約洗衣機維修 2030-01-10 10:00")
        send(page, "先不要")
        expect(page.get_by_role("button", name="確認建立預約", exact=True)).to_have_count(0)
        assert len(db_bookings(live_server)) == 1

        page.locator(".demo summary").click()
        page.locator("#fault").select_option("after_commit")
        send(page, "預約洗衣機維修 2030-01-10 10:00")
        page.get_by_role("button", name="確認建立預約", exact=True).click()
        expect(page.locator("#notice-text")).to_contain_text("逾時")
        page.locator("#recover").click()
        expect(page.locator("#booking-count")).to_have_text("1")
        assert len(db_bookings(live_server)) == 2

        page.locator("#fault").select_option("before_commit")
        send(page, "預約冷氣維修 2030-01-11 16:00")
        page.get_by_role("button", name="確認建立預約", exact=True).click()
        expect(page.locator("#confirmation")).to_contain_text("待查證")
        assert len(db_bookings(live_server)) == 2
        live_server["restart"]()
        page.reload()
        expect(page.locator("#booking-count")).to_have_text("2")
        assert len(db_bookings(live_server)) == 3
        page.screenshot(path=str(artifacts / "desktop-verified.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=str(artifacts / "mobile-verified.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert errors == []
        browser.close()


def test_new_reversal_after_lost_message_response_sends_new_intent(live_server):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(live_server["url"])
        page.wait_for_load_state("networkidle")

        def lose_response(route):
            route.fetch()
            route.abort("failed")

        page.route("**/api/messages", lose_response, times=1)
        page.locator("#message").fill("預約冷氣維修 2030-01-08 10:00")
        page.locator("#send").click()
        expect(page.locator("#retry")).to_be_visible()
        with page.expect_request("**/api/messages") as sent:
            page.get_by_role("button", name="先不要", exact=True).click()
        assert "先不要" in sent.value.post_data_json["text"]
        expect(page.locator("#confirmation")).to_contain_text("目前沒有待確認操作")
        assert db_bookings(live_server) == []
        browser.close()


def test_form_retry_keeps_same_request_id_after_lost_response(live_server):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(live_server["url"])
        page.wait_for_load_state("networkidle")
        first_request = []

        def lose_response(route):
            first_request.append(route.request.post_data_json)
            route.fetch()
            route.abort("failed")

        page.route("**/api/proposals", lose_response, times=1)
        page.locator(".booking-form-panel summary").click()
        page.locator("#date").fill("2030-01-08")
        page.get_by_role("button", name="建立待確認操作", exact=True).click()
        expect(page.locator("#retry")).to_be_visible()
        with page.expect_request("**/api/proposals") as sent:
            page.locator("#retry").click()
        assert sent.value.post_data_json["request_id"] == first_request[0]["request_id"]
        expect(page.get_by_role("button", name="確認建立預約", exact=True)).to_be_visible()
        assert db_bookings(live_server) == []
        browser.close()
