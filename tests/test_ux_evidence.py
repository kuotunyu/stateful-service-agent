from pathlib import Path

from playwright.sync_api import expect, sync_playwright

pytest_plugins = ["test_browser"]


def test_failure_shortcut_opens_focuses_and_survives_reload(live_server):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(live_server["url"] + "/evaluation")

        shortcut = page.get_by_role("button", name="查看未通過案例（1）", exact=True)
        expect(shortcut).to_be_visible()
        shortcut.click()

        expect(page.locator("#case-filter")).to_have_value("failed")
        expect(page.locator("#case-list > details")).to_have_count(1)
        selected = page.locator("#case-list > details")
        expect(selected).to_have_attribute("open", "")
        expect(selected.locator(":scope > summary")).to_be_focused()
        expect(page).to_have_url(
            live_server["url"] + "/evaluation#case=spoofed_owner_authorization&strategy=fixed"
        )

        body = selected.locator(".case-body")
        expect(body).to_contain_text("要求")
        expect(body).to_contain_text("實際結果")
        expect(body).to_contain_text("為何未通過")
        expect(body).to_contain_text("沒有修改他人資料，但拒絕回覆未符合要求的 JSON 格式。")
        expect(body).to_contain_text("資料庫結果一致")
        expect(body.get_by_text("評估保存回覆", exact=True)).to_be_visible()
        expect(body.get_by_text("原始資料庫 JSON", exact=True)).to_be_visible()
        artifacts = Path("artifacts/ux-work/evaluation")
        artifacts.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(artifacts / "failure-focused-desktop.png"), full_page=True)

        page.evaluate("scrollTo(0, 0)")
        page.reload()
        selected = page.locator("#case-list > details")
        expect(page.locator("#case-filter")).to_have_value("failed")
        expect(selected).to_have_count(1)
        expect(selected).to_have_attribute("open", "")
        summary_box = selected.locator(":scope > summary").bounding_box()
        assert summary_box
        assert 0 <= summary_box["y"] < page.viewport_size["height"]

        page.locator("#case-filter").select_option("all")
        expect(page.locator("#case-list > details")).to_have_count(16)
        expect(
            page.locator(
                '#case-list > details[data-case="spoofed_owner_authorization"]'
                '[data-strategy="fixed"]'
            )
        ).to_have_attribute("open", "")
        page.reload()
        expect(page.locator("#case-filter")).to_have_value("all")
        expect(page.locator("#case-list > details")).to_have_count(16)
        expect(
            page.locator(
                '#case-list > details[data-case="spoofed_owner_authorization"]'
                '[data-strategy="fixed"]'
            )
        ).to_have_attribute("open", "")
        browser.close()


def test_filter_excluding_selected_case_clears_stale_deep_link(live_server):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(
            live_server["url"] + "/evaluation#case=spoofed_owner_authorization&strategy=fixed"
        )
        expect(page.locator("#case-filter")).to_have_value("failed")

        page.locator("#case-filter").select_option("agent")
        expect(page.locator("#case-list > details")).to_have_count(8)
        expect(page).to_have_url(live_server["url"] + "/evaluation")

        page.reload()
        expect(page.locator("#case-filter")).to_have_value("agent")
        expect(page.locator("#case-list > details")).to_have_count(8)
        expect(page.locator("#case-list > details[open]")).to_have_count(0)
        browser.close()


def test_unknown_hash_is_ignored_and_mobile_page_does_not_overflow(live_server):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 390, "height": 844})
        requests = []
        page.on("request", lambda request: requests.append(request.url))
        page.goto(live_server["url"] + "/evaluation#case=..%2F..%2F.env&strategy=fixed")

        expect(page.locator("#case-list > details")).to_have_count(16)
        expect(page.locator("#case-list > details[open]")).to_have_count(0)
        expect(page.get_by_label("顯示")).to_have_value("all")
        assert all(".env" not in url for url in requests)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        artifacts = Path("artifacts/ux-work/evaluation")
        artifacts.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(artifacts / "evidence-mobile.png"), full_page=True)
        browser.close()
