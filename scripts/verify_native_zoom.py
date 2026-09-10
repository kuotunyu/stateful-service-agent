"""Verify native Edge tab zoom using an isolated profile, extension and test server."""

import argparse
import base64
import json
import sys
import tempfile
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root), str(root / "tests")]
    from playwright.sync_api import expect, sync_playwright
    from test_browser import db_bookings, live_server, send

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=root / "artifacts/native-zoom-2026-09-10")
    output = parser.parse_args().output
    output.mkdir(exist_ok=False)
    with tempfile.TemporaryDirectory() as temporary:
        temporary = Path(temporary)
        extension = temporary / "extension"
        extension.mkdir()
        (extension / "manifest.json").write_text(
            json.dumps(
                {
                    "manifest_version": 3,
                    "name": "Isolated native zoom verification",
                    "version": "1.0",
                    "permissions": ["tabs"],
                    "background": {"service_worker": "worker.js"},
                }
            )
        )
        (extension / "worker.js").write_text("chrome.runtime.onInstalled.addListener(() => {});")
        fixture = live_server.__wrapped__(temporary)
        server = next(fixture)
        try:
            with sync_playwright() as p:
                context = p.chromium.launch_persistent_context(
                    str(temporary / "profile"),
                    channel="msedge",
                    headless=True,
                    ignore_default_args=["--disable-extensions"],
                    args=[
                        f"--disable-extensions-except={extension}",
                        f"--load-extension={extension}",
                    ],
                    viewport={"width": 1280, "height": 900},
                    timeout=60000,
                )
                try:
                    worker = (
                        context.service_workers[0]
                        if context.service_workers
                        else context.wait_for_event("serviceworker", timeout=15000)
                    )
                    page = context.new_page()
                    page.goto(server["url"])
                    page.wait_for_load_state("networkidle")
                    zoom = worker.evaluate(
                        """async url => {
                            const tabs = await chrome.tabs.query({});
                            const tab = tabs.find(t => t.url.startsWith(url));
                            await chrome.tabs.setZoom(tab.id, 2);
                            return await chrome.tabs.getZoom(tab.id);
                        }""",
                        server["url"],
                    )
                    assert zoom == 2
                    page.wait_for_function("innerWidth === 640")
                    measurements = []

                    def capture(stage):
                        values = page.evaluate(
                            """({width:innerWidth, scrollWidth:document.documentElement.scrollWidth,
                                dpr:devicePixelRatio,
                                cssZoom:getComputedStyle(document.documentElement).zoom})"""
                        )
                        assert values["width"] == values["scrollWidth"] == 640
                        assert values["cssZoom"] == "1" and values["dpr"] == 2
                        measurements.append({"stage": stage, **values})
                        # Avoid Playwright CSS-coordinate clips at native zoom;
                        # request the compositor's visible viewport directly.
                        page.wait_for_timeout(350)
                        session = context.new_cdp_session(page)
                        shot = session.send(
                            "Page.captureScreenshot",
                            {"format": "png", "captureBeyondViewport": False},
                        )
                        session.detach()
                        (output / f"{stage}.png").write_bytes(base64.b64decode(shot["data"]))

                    capture("01-home")
                    send(page, "預約洗衣機維修 2030-05-01 14:00")
                    page.locator("#confirmation-next").focus()
                    page.locator("#confirmation-next").press("Enter")
                    expect(page.locator("#confirmation-heading")).to_be_focused()
                    assert db_bookings(server) == []
                    page.get_by_role("button", name="確認建立預約", exact=True).press("Enter")
                    expect(page.locator("#booking-count")).to_have_text("1")
                    page.get_by_role("button", name="改期", exact=True).press("Enter")
                    page.locator("#reschedule-date").fill("2030-05-02")
                    page.locator("#reschedule-time").select_option("16:00")
                    page.get_by_role("button", name="預覽改期", exact=True).press("Enter")
                    page.locator("#confirmation-heading").scroll_into_view_if_needed()
                    capture("02-reschedule-preview")
                    assert db_bookings(server)[0]["version"] == 1
                    page.get_by_role("button", name="確認改期預約", exact=True).press("Enter")
                    expect(page.locator("#confirmation")).to_contain_text("已改期預約")
                    assert db_bookings(server)[0]["slot"] == "2030-05-02T16:00:00+08:00"
                    assert db_bookings(server)[0]["version"] == 2
                    page.goto(server["url"] + "/evaluation")
                    expect(page.locator("#case-list > details")).to_have_count(16)
                    page.locator("#view-failures").press("Enter")
                    expect(page.locator("#case-list > details")).to_have_count(1)
                    capture("03-evaluation")
                    report = {
                        "browser": context.browser.version,
                        "native_zoom": zoom,
                        "measurements": measurements,
                        "booking": db_bookings(server),
                        "screen_reader_tested": False,
                    }
                    (output / "result.json").write_text(
                        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                    print(json.dumps(report, ensure_ascii=False))
                finally:
                    context.close()
        finally:
            fixture.close()


if __name__ == "__main__":
    main()
