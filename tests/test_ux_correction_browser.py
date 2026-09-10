from playwright.sync_api import expect, sync_playwright
from test_browser import db_bookings, send

pytest_plugins = ["test_browser"]


def test_bad_time_then_correction_completes_only_after_new_confirmation(live_server):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(live_server["url"])
        send(page, "預約洗衣機維修 2030-01-08 10:00")
        previous = page.locator("#confirmation [data-operation-id]").get_attribute(
            "data-operation-id"
        )
        send(page, "改成 2030-01-08 15:00")
        expect(page.locator("#confirmation")).to_contain_text("操作草案")
        expect(page.get_by_role("button", name="確認建立預約", exact=True)).to_have_count(0)
        expect(page.get_by_role("button", name="用表單選時間", exact=True)).to_be_visible()
        page.get_by_role("button", name="用表單選時間", exact=True).click()
        expect(page.locator("#service")).to_have_value("洗衣機維修")
        expect(page.locator("#date")).to_have_value("2030-01-08")
        assert db_bookings(live_server) == []
        send(page, "那就 16:00")
        expect(page.locator("#confirmation")).to_contain_text("洗衣機維修")
        expect(page.locator("#confirmation")).to_contain_text("16:00")
        assert (
            page.locator("#confirmation [data-operation-id]").get_attribute("data-operation-id")
            != previous
        )
        assert db_bookings(live_server) == []
        page.get_by_role("button", name="確認建立預約", exact=True).click()
        expect(page.locator("#booking-count")).to_have_text("1")
        assert db_bookings(live_server)[0]["slot"] == "2030-01-08T16:00:00+08:00"
        browser.close()
