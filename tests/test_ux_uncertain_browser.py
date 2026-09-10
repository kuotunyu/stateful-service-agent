import re

from playwright.sync_api import expect, sync_playwright
from test_browser import db_bookings, send

pytest_plugins = ["test_browser"]


def test_lost_confirmation_delivery_stays_uncertain_past_expiry_until_verified(live_server):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.clock.install()
        page.goto(live_server["url"])
        send(page, "預約冷氣維修 2030-01-08 10:00")
        confirmation = page.locator("#confirmation")
        expect(confirmation.get_by_role("button", name="確認建立預約", exact=True)).to_be_visible()
        assert db_bookings(live_server) == []
        delivered_to_server = []

        def lose_confirmation_delivery(route):
            response = route.fetch()
            assert response.ok
            delivered_to_server.append(response.json()["status"])
            route.abort("failed")

        def block_state_read(route):
            route.abort("failed")

        # Commit through the real endpoint, then lose only the HTTP delivery.
        # State reads remain unavailable, so the browser cannot verify the commit.
        page.route("**/api/state", block_state_read)
        page.route("**/api/operations/*/confirm", lose_confirmation_delivery)
        confirmation.get_by_role("button", name="確認建立預約", exact=True).click()
        expect(page.locator("#notice-text")).to_contain_text(re.compile("未知|待查證|先查證"))
        assert delivered_to_server == ["committed"]
        committed = db_bookings(live_server)
        assert len(committed) == 1 and committed[0]["version"] == 1
        expect(page.locator("#result")).not_to_contain_text(re.compile("尚未修改|等待.*確認"))
        expect(page.locator("#result")).to_contain_text(re.compile("未知|待查證|先查證"))

        page.clock.fast_forward(301_000)
        expect(confirmation).not_to_contain_text("預約尚未修改")
        expect(confirmation).to_contain_text(re.compile("未知|待查證|先查證"))
        expect(confirmation.get_by_role("button", name="重新填寫", exact=True)).to_have_count(0)
        expect(confirmation.get_by_role("button", name="確認建立預約", exact=True)).to_have_count(0)
        expect(
            confirmation.get_by_role("button", name="查證結果與恢復", exact=True)
        ).to_be_visible()
        expect(page.locator("#result")).not_to_contain_text(re.compile("尚未修改|等待.*確認"))
        assert db_bookings(live_server) == committed
        assert delivered_to_server == ["committed"]

        page.unroute("**/api/state", block_state_read)
        confirmation.get_by_role("button", name="查證結果與恢復", exact=True).click()
        expect(page.locator("#booking-count")).to_have_text("1")
        expect(page.locator("#result")).to_contain_text("已查證")
        with page.expect_response("**/api/recover"):
            page.locator("#recover").click()
        expect(page.locator("#booking-count")).to_have_text("1")
        assert db_bookings(live_server) == committed
        assert delivered_to_server == ["committed"]
        browser.close()
