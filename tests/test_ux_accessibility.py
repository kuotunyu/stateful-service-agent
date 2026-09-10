"""Browser geometry and keyboard checks; these do not replace screen-reader testing."""

import re

import pytest
from playwright.sync_api import expect, sync_playwright
from test_browser import db_bookings, send

pytest_plugins = ["test_browser"]


def tab_to(page, target):
    """Reach controls through the real tab order, without scripted focus or clicks."""
    expect(target).to_be_visible()
    for _ in range(60):
        if target.evaluate("element => element === document.activeElement"):
            return
        page.keyboard.press("Tab")
    raise AssertionError("Control was not reachable within one keyboard journey")


def test_keyboard_booking_journey_requires_confirmation(live_server):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(live_server["url"])
        expect(page.locator(".welcome")).to_be_visible()

        def activate(name):
            tab_to(page, page.get_by_role("button", name=name, exact=True))
            page.keyboard.press("Enter")

        def propose(text, action):
            tab_to(page, page.get_by_role("textbox", name="你的訊息", exact=True))
            page.keyboard.insert_text(text)
            page.keyboard.press("Enter")
            expect(page.get_by_role("button", name="確認" + action, exact=True)).to_be_visible()
            activate("已準備好，查看確認單")
            expect(page.locator("#confirmation-heading")).to_be_focused()

        activate("查看目前預約")
        expect(page.locator("#notice-text")).to_contain_text("目前有 0 筆")
        propose("預約冷氣維修 2030-01-08 10:00", "建立預約")
        assert db_bookings(live_server) == []
        activate("放棄這次操作")
        expect(page.locator("#result")).to_contain_text("取消")
        assert db_bookings(live_server) == []

        propose("預約冷氣維修 2030-01-08 10:00", "建立預約")
        assert db_bookings(live_server) == []
        activate("確認建立預約")
        expect(page.locator("#booking-count")).to_have_text("1")
        original = db_bookings(live_server)
        assert len(original) == 1 and original[0]["version"] == 1

        propose("改成 2030-01-09 14:00", "改期預約")
        assert db_bookings(live_server) == original
        activate("確認改期預約")
        expect(page.locator("#bookings")).to_contain_text("2030/01/09")
        changed = db_bookings(live_server)
        assert len(changed) == 1 and changed[0]["version"] == 2
        assert changed[0]["slot"] == "2030-01-09T14:00:00+08:00"

        propose("取消預約", "取消預約")
        assert db_bookings(live_server) == changed
        activate("確認取消預約")
        expect(page.locator("#booking-count")).to_have_text("0")
        cancelled = db_bookings(live_server)
        assert len(cancelled) == 1 and cancelled[0]["status"] == "cancelled"
        assert cancelled[0]["version"] == 3
        assert not errors
        browser.close()


def contrast(first, second):
    def luminance(color):
        values = [int(value) / 255 for value in re.findall(r"\d+", color)[:3]]
        values = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in values]
        return sum(v * weight for v, weight in zip(values, [0.2126, 0.7152, 0.0722]))

    bright, dark = sorted([luminance(first), luminance(second)], reverse=True)
    return (bright + 0.05) / (dark + 0.05)


@pytest.mark.parametrize("width", [390, 680, 900, 1280])
def test_readable_layout_controls_and_reduced_motion(live_server, width):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": width, "height": 844}, reduced_motion="reduce")
        page.goto(live_server["url"])
        expect(page.locator(".welcome")).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        for selector in ["#send", "#query-bookings", "#refresh"]:
            box = page.locator(selector).bounding_box()
            assert box and box["width"] >= 44 and box["height"] >= 44, (width, selector, box)
        styles = page.locator("#send").evaluate(
            "e => {const s = getComputedStyle(e); return [s.color, s.backgroundColor]}"
        )
        assert contrast(*styles) >= 4.5
        border = page.locator("#message").evaluate("e => getComputedStyle(e).borderTopColor")
        assert contrast(border, "rgb(255, 255, 255)") >= 3
        assert page.evaluate("getComputedStyle(document.documentElement).scrollBehavior") == "auto"
        if width <= 680:
            assert (
                page.locator(".welcome p").first.evaluate(
                    "e => parseFloat(getComputedStyle(e).fontSize)"
                )
                >= 16
            )
        browser.close()


def test_keyboard_composition_and_refresh_preserve_chat_nodes_and_scroll(live_server):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        page.goto(live_server["url"])
        expect(page.locator(".welcome")).to_be_visible()
        message = page.locator("#message")
        message.fill("查詢")
        message.press("Shift+Enter")
        expect(message).to_have_value("查詢\n")
        message.dispatch_event("keydown", {"key": "Enter", "isComposing": True})
        expect(page.locator("#messages .chat-entry")).to_have_count(0)
        message.press("Enter")
        expect(page.locator("#messages .chat-entry")).to_have_count(2)
        send(page, "說明" * 200)
        send(page, "規則" * 200)
        expect(page.locator("#messages .chat-entry")).to_have_count(6)
        page.evaluate(
            "window.uxEntry = document.querySelector('[data-message-key]'); "
            "document.getElementById('messages').scrollTop = 0"
        )
        page.locator("#refresh").click()
        expect(page.locator("#notice-text")).to_contain_text("目前有")
        assert page.evaluate("window.uxEntry === document.querySelector('[data-message-key]')")
        assert page.locator("#messages").evaluate("e => e.scrollTop") == 0
        browser.close()
