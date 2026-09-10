"""Record the free local demo against a disposable server and SQLite database."""

import json
import sys
import tempfile
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root), str(root / "tests")]
    from playwright.sync_api import expect, sync_playwright
    from test_browser import db_bookings, live_server, send

    output = root / "artifacts/demo-2026-09-10"
    output.mkdir(exist_ok=False)
    checkpoints = []
    with tempfile.TemporaryDirectory() as temporary:
        fixture = live_server.__wrapped__(Path(temporary))
        server = next(fixture)
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, slow_mo=180)
                context = browser.new_context(
                    viewport={"width": 1280, "height": 900},
                    record_video_dir=str(output),
                    record_video_size={"width": 1280, "height": 900},
                )
                page = context.new_page()
                video = page.video
                page.goto(server["url"])

                def checkpoint(name, count):
                    actual = db_bookings(server)
                    assert len(actual) == count
                    checkpoints.append({"stage": name, "bookings": actual})
                    page.locator("#confirmation-panel").scroll_into_view_if_needed()
                    page.wait_for_timeout(1800)  # Reading time in the recorded demo.
                    page.screenshot(path=str(output / f"{name}.png"))

                send(page, "預約冷氣維修 2030-04-01 10:00")
                checkpoint("01-before-confirmation", 0)
                page.get_by_role("button", name="確認建立預約", exact=True).click()
                expect(page.locator("#booking-count")).to_have_text("1")
                checkpoint("02-confirmed", 1)

                send(page, "預約洗衣機維修 2030-04-02 14:00")
                send(page, "先不要")
                expect(page.get_by_role("button", name="確認建立預約", exact=True)).to_have_count(0)
                checkpoint("03-reversed-no-extra-booking", 1)

                page.locator(".demo summary").click()
                page.locator("#fault").select_option("after_commit")
                send(page, "預約洗衣機維修 2030-04-02 14:00")
                page.get_by_role("button", name="確認建立預約", exact=True).click()
                expect(page.locator("#notice-text")).to_contain_text("逾時")
                page.locator("#recover").click()
                expect(page.locator("#booking-count")).to_have_text("2")
                checkpoint("04-lost-reply-recovered-once", 2)

                page.locator("#fault").select_option("before_commit")
                send(page, "預約冷氣維修 2030-04-03 16:00")
                page.get_by_role("button", name="確認建立預約", exact=True).click()
                expect(page.locator("#confirmation")).to_contain_text("查證")
                checkpoint("05-before-process-restart", 2)
                server["restart"]()
                page.reload()
                expect(page.locator("#booking-count")).to_have_text("3")
                checkpoint("06-restart-recovered-once", 3)
                assert all(booking["version"] == 1 for booking in db_bookings(server))
                context.close()
                video.save_as(str(output / "repair-desk-demo.webm"))
                browser.close()
        finally:
            fixture.close()
    (output / "checkpoints.json").write_text(
        json.dumps(checkpoints, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Recorded {len(checkpoints)} verified stages: {output / 'repair-desk-demo.webm'}")


if __name__ == "__main__":
    main()
