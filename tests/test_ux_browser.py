from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from test_browser import db_bookings, send

pytest_plugins = ["test_browser"]


def test_date_year_is_limited_and_invalid_year_cannot_propose(live_server):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(live_server["url"])
        create_booking(page)
        page.get_by_role("button", name="改期", exact=True).click()
        posts = []
        page.on("request", lambda r: posts.append(r.url) if r.method == "POST" else None)
        for selector in ("#date", "#reschedule-date"):
            expect(page.locator(selector)).to_have_attribute("max", "9999-12-31")
        # Chromium's en-US date editor orders its segments month/day/year.
        date = page.locator("#reschedule-date")
        for _ in range(3):
            date.press("ArrowLeft")
        date.press("ArrowRight")
        date.press("ArrowRight")
        date.press_sequentially("111111")
        assert len(date.input_value().split("-")[0]) == 4
        # A programmatic/pasted extended year must also fail application validation.
        page.locator("#reschedule-date").fill("11111-11-11")
        page.get_by_role("button", name="預覽改期", exact=True).click()
        expect(page.locator("#reschedule-error")).to_contain_text("四位數")
        expect(page.locator("#reschedule-date")).to_be_focused()
        assert posts == []
        assert db_bookings(live_server)[0]["version"] == 1
        page.locator("#reschedule-date").fill("2030-01-09")
        page.get_by_role("button", name="預覽改期", exact=True).click()
        expect(page.get_by_role("button", name="確認改期預約", exact=True)).to_be_visible()
        browser.close()


def create_booking(page):
    send(page, "預約冷氣維修 2030-01-08 10:00")
    page.get_by_role("button", name="確認建立預約", exact=True).click()
    expect(page.locator("#booking-count")).to_have_text("1")


def test_first_screen_and_query_controls_preserve_confirmation(live_server):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.goto(live_server["url"])
        artifacts = Path("artifacts/ux-work")
        artifacts.mkdir(parents=True, exist_ok=True)
        start = page.get_by_role("button", name="冷氣維修・明天 10:00", exact=True)
        expect(start).to_be_visible()
        box = start.bounding_box()
        assert box and box["y"] + box["height"] <= 844
        expect(page.locator("#model-details")).not_to_have_attribute("open", "")
        for selector in ("#send", "#query-bookings"):
            control = page.locator(selector).bounding_box()
            assert control and control["width"] >= 44 and control["height"] >= 44
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(artifacts / "first-screen-mobile.png"), full_page=True)
        page.set_viewport_size({"width": 1280, "height": 720})
        page.reload()
        desktop = start.bounding_box()
        assert desktop and desktop["y"] + desktop["height"] <= 720
        page.screenshot(path=str(artifacts / "first-screen-desktop.png"), full_page=True)
        send(page, "預約冷氣維修 2030-01-08 10:00")
        operation = page.locator("#confirmation [data-operation-id]").get_attribute(
            "data-operation-id"
        )
        for selector in ("#query-bookings", "#refresh"):
            page.locator(selector).click()
            expect(page.locator("#confirmation [data-operation-id]")).to_have_attribute(
                "data-operation-id", operation
            )
            expect(page.locator("#notice-text")).to_contain_text("待確認內容已保留")
        browser.close()


def test_inline_reschedule_has_no_opening_post_and_preserves_edit(live_server):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        posts = []
        page.on(
            "request",
            lambda request: (
                posts.append(request.url)
                if request.method == "POST" and "/api/proposals" in request.url
                else None
            ),
        )
        page.goto(live_server["url"])
        create_booking(page)
        before = len(posts)
        page.get_by_role("button", name="改期", exact=True).click()
        expect(page.locator("#reschedule-form")).to_be_visible()
        assert len(posts) == before
        page.locator("#reschedule-date").fill("2030-01-09")
        page.locator("#reschedule-time").select_option("16:00")
        page.locator("#refresh").click()
        expect(page.locator("#reschedule-date")).to_have_value("2030-01-09")
        Path("artifacts/ux-work").mkdir(parents=True, exist_ok=True)
        page.screenshot(path="artifacts/ux-work/reschedule-editor.png", full_page=True)
        page.get_by_role("button", name="預覽改期", exact=True).click()
        expect(page.get_by_role("button", name="確認改期預約", exact=True)).to_be_visible()
        assert db_bookings(live_server)[0]["slot"] == "2030-01-08T10:00:00+08:00"
        browser.close()


def test_past_inline_date_stays_editable_without_post(live_server):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(live_server["url"])
        create_booking(page)
        page.get_by_role("button", name="改期", exact=True).click()
        page.locator("#reschedule-date").fill("2020-01-01")
        count = 0

        def count_proposal(request):
            nonlocal count
            if request.method == "POST" and "/api/proposals" in request.url:
                count += 1

        page.on("request", count_proposal)
        page.get_by_role("button", name="預覽改期", exact=True).click()
        expect(page.locator("#reschedule-date")).to_be_focused()
        expect(page.locator("#reschedule-date")).to_have_attribute("aria-invalid", "true")
        Path("artifacts/ux-work").mkdir(parents=True, exist_ok=True)
        page.screenshot(path="artifacts/ux-work/date-error.png", full_page=True)
        assert count == 0
        browser.close()


def test_cancelled_booking_moves_to_collapsed_history(live_server):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(live_server["url"])
        create_booking(page)
        page.get_by_role("button", name="取消預約", exact=True).click()
        page.get_by_role("button", name="確認取消預約", exact=True).click()
        expect(page.locator("#bookings")).to_contain_text("目前沒有有效預約")
        expect(page.locator("#booking-history summary")).to_contain_text("已取消紀錄（1）")
        expect(page.locator("#booking-history")).not_to_have_attribute("open", "")
        browser.close()


def test_next_step_focuses_confirmation_and_countdown_expires_without_submit(live_server):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.clock.install()
        page.goto(live_server["url"])
        send(page, "預約冷氣維修 2030-01-08 10:00")
        page.locator("#confirmation-next").click()
        expect(page.locator("#confirmation")).to_contain_text("2030/01/08")
        expect(page.locator("#confirmation-heading")).to_be_focused()
        expect(page.locator("#confirmation-expiry")).to_contain_text("請在")
        page.get_by_role("button", name="確認建立預約", exact=True).focus()
        page.clock.fast_forward(301_000)
        expect(page.locator("#confirmation-expiry")).to_contain_text("確認已過期")
        expect(page.locator("#confirmation-expiry")).to_be_focused()
        expect(page.locator("#result")).to_contain_text("確認已過期")
        expect(page.locator("#result")).not_to_contain_text("正在等待你的確認")
        page.locator("#refresh").click()
        expect(page.locator("#result")).to_contain_text("確認已過期")
        Path("artifacts/ux-work").mkdir(parents=True, exist_ok=True)
        page.screenshot(path="artifacts/ux-work/expired-confirmation.png", full_page=True)
        expect(page.get_by_role("button", name="確認建立預約", exact=True)).to_have_count(0)
        expect(page.get_by_role("button", name="重新填寫", exact=True)).to_be_visible()
        assert db_bookings(live_server) == []
        browser.close()


def test_saved_booking_keeps_year_visible(live_server):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.goto(live_server["url"])
        create_booking(page)
        expect(page.locator("#bookings")).to_contain_text("2030/01/08")
        expect(page.locator("#result")).to_contain_text("2030/01/08")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        browser.close()


def test_server_field_error_preserves_inline_reschedule_values(live_server):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(live_server["url"])
        create_booking(page)
        page.get_by_role("button", name="改期", exact=True).click()
        page.locator("#reschedule-date").fill("2030-01-09")
        page.locator("#reschedule-time").select_option("16:00")
        page.route(
            "**/api/proposals",
            lambda route: route.fulfill(
                status=200,
                json={
                    "rejected": True,
                    "text": "時段已失效，請重新選擇。",
                    "validation": {"code": "unsupported_time", "field": "time"},
                },
            ),
            times=1,
        )
        page.get_by_role("button", name="預覽改期", exact=True).click()
        expect(page.locator("#reschedule-date")).to_have_value("2030-01-09")
        expect(page.locator("#reschedule-time")).to_have_value("16:00")
        expect(page.locator("#reschedule-time")).to_have_attribute("aria-invalid", "true")
        expect(page.locator("#reschedule-time")).to_be_focused()
        expect(page.locator("#reschedule-error")).to_have_text("時段已失效，請重新選擇。")
        browser.close()


def test_server_expiry_rejection_overrides_local_countdown(live_server):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(live_server["url"])
        send(page, "預約冷氣維修 2030-01-08 10:00")
        page.route(
            "**/api/operations/*/confirm",
            lambda route: route.fulfill(
                status=409, json={"detail": "確認已過期，請重新提出操作。"}
            ),
            times=1,
        )
        page.get_by_role("button", name="確認建立預約", exact=True).click()
        expect(page.locator("#confirmation-expiry")).to_have_text("確認已過期，預約尚未修改")
        expect(page.get_by_role("button", name="確認建立預約", exact=True)).to_have_count(0)
        expect(page.get_by_role("button", name="重新填寫", exact=True)).to_be_visible()
        assert db_bookings(live_server) == []
        browser.close()
