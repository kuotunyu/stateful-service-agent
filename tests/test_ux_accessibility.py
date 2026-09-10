"""Browser geometry and keyboard checks; these do not replace screen-reader testing."""

import re

import pytest
from playwright.sync_api import expect, sync_playwright
from test_browser import send

pytest_plugins = ["test_browser"]


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
