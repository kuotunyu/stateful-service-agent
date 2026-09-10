from playwright.sync_api import expect, sync_playwright

from tests.test_browser import live_server  # noqa: F401


def test_mode_label_and_interrupt_allow_next_intent(live_server):  # noqa: F811
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(live_server["url"])
        expect(page.locator("#mode")).to_have_value("mock")
        # Hold the HTTP delivery before the server sees the first request.
        held = []
        page.route("**/api/messages", lambda route: held.append(route))
        page.locator("#message").fill("預約冷氣維修 2030-01-08 10:00")
        page.locator("#send").click()
        expect(page.locator("#interrupt")).to_be_visible()
        page.locator("#interrupt").click()
        expect(page.locator("#send")).to_be_enabled()
        held.pop().continue_()
        page.unroute("**/api/messages")
        page.locator("#message").fill("查詢我的預約")
        page.locator("#send").click()
        expect(page.locator("#messages")).to_contain_text("0 筆有效預約")
        expect(page.locator("#booking-count")).to_have_text("0")
        expect(page.get_by_role("button", name="確認建立預約", exact=True)).to_have_count(0)
        browser.close()


def test_browser_live_modes_timeout_then_replay_without_second_model_call(tmp_path):
    import socket
    import threading
    import time

    import uvicorn

    from agent.app import create_app

    release = threading.Event()
    calls = []

    class SlowModel:
        def respond(self, messages, config):
            calls.append(messages)
            assert release.wait(25)
            if len(calls) == 1:
                return {
                    "tool": "propose",
                    "arguments": {
                        "action": "create",
                        "service": "冷氣維修",
                        "slot": "2030-01-08T10:00:00+08:00",
                    },
                }
            return {"tool": "finish", "arguments": {"text": "這是測試模型的查詢回覆。"}}

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(tmp_path / "browser.db", model=SlowModel()),
            host="127.0.0.1",
            port=port,
            log_level="error",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{port}")
            expect(page.locator('#mode option[value="fixed"]')).to_be_enabled()
            page.locator("#model-details summary").click()
            page.locator("#mode").select_option("fixed")
            expect(page.locator("#mode-help")).to_contain_text("可能產生 API 費用")
            page.locator("#message").fill("預約冷氣維修")
            page.locator("#send").click()
            expect(page.locator("#retry")).to_be_visible(timeout=20000)
            release.set()
            expect(page.locator("#messages")).to_contain_text("固定流程 + LLM", timeout=5000)
            page.locator("#retry").click()
            confirm = page.get_by_role("button", name="確認建立預約", exact=True)
            expect(confirm).to_be_enabled()
            assert len(calls) == 1
            confirm.click()
            expect(page.locator("#booking-count")).to_have_text("1")
            page.locator("#mode").select_option("agent")
            page.locator("#message").fill("查詢")
            page.locator("#send").click()
            expect(page.locator("#messages")).to_contain_text("單一 Agent")
            expect(page.locator("#messages")).to_contain_text("固定流程 + LLM")
            assert len(calls) == 2
            browser.close()
    finally:
        release.set()
        server.should_exit = True
        thread.join(timeout=5)
