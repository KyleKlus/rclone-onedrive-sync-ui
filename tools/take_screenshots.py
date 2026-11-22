"""!
@file take_screenshots.py
@brief Takes the screenshots used in the README (docs/screenshots/).

Starts the real app on a free port with tools/demo_rclone.py instead of rclone, fills it
with three example folder pairs and photographs the UI in a headless Chromium.
Needs `pip install playwright` and `playwright install chromium` (only for this script).

Usage:
    python tools/take_screenshots.py [--out docs/screenshots] [--home /home/you]

--home is the folder that holds the example local folders (default: a temporary one);
it only decides which paths show up in the pictures. Folders that do not exist are created.
"""

import argparse
import os
import shutil
import stat
import sys
import tempfile
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import Application

DEMO_RCLONE = Path(__file__).resolve().parent / "demo_rclone.py"
VIEWPORT = {"width": 1360, "height": 980}
SCALE = 1.5

PAIRS = (
    ("Photos", "Pictures", "icloud:Photos"),
    ("Documents", "Documents", "onedrive:Documents"),
    ("Work", "Work", "gdrive:Projects"),
)


def start_app(data_dir: Path) -> Application:
    """!
    @brief Start the app in a background thread.
    @param data_dir Where the app keeps its pairs.json.
    @return The running application (call shutdown() when done).
    """
    app = Application(data_dir=data_dir, rclone_binary=str(DEMO_RCLONE), port=0)
    threading.Thread(target=app.run, daemon=True).start()
    return app


def api(page, method: str, path: str, body=None):
    """!
    @brief Call the app's API from inside the page.
    @param page The Playwright page.
    @param method The HTTP method.
    @param path The URL path.
    @param body Optional JSON body.
    @return The decoded JSON answer.
    """
    return page.evaluate(
        """([method, path, body]) => fetch(path, {
            method, headers: {'Content-Type': 'application/json'},
            body: body ? JSON.stringify(body) : undefined,
        }).then((response) => response.json())""",
        [method, path, body],
    )


def add_pairs(page, home: Path) -> None:
    """!
    @brief Create the three example folder pairs.
    @param page The Playwright page.
    @param home The folder that holds the local folders.
    """
    for name, folder, remote in PAIRS:
        local = home / folder
        local.mkdir(parents=True, exist_ok=True)
        api(page, "POST", "/api/pairs", {
            "name": name, "local_path": str(local), "remote": remote,
            "max_size": "50M", "exclusions": ["~$*", "*.tmp", ".DS_Store"],
        })
    page.reload()
    page.wait_for_selector("#pair-list li")
    page.evaluate("document.fonts.ready")
    page.wait_for_timeout(800)


def new_page(playwright, base_url: str):
    """!
    @brief Open the app in a fresh browser page.
    @param playwright The Playwright instance.
    @param base_url The address of the running app.
    @return A tuple (browser, page).
    """
    browser = playwright.chromium.launch()
    context = browser.new_context(
        viewport=VIEWPORT, device_scale_factor=SCALE, bypass_csp=True, permissions=["clipboard-read", "clipboard-write"]
    )
    page = context.new_page()
    page.goto(base_url)
    page.wait_for_selector("#pair-add-button")
    return browser, page


def scene_run(playwright, workdir: Path, home: Path, out: Path) -> None:
    """!
    @brief Photograph the idle overview, a running sync and the finished state.
    @param playwright The Playwright instance.
    @param workdir A temporary folder for the app's data.
    @param home The folder that holds the local folders.
    @param out The folder the pictures are written to.
    """
    app = start_app(workdir / "run")
    browser, page = new_page(playwright, f"http://127.0.0.1:{app.web_server.port}")
    add_pairs(page, home)
    page.screenshot(path=str(out / "overview.png"))

    page.click("#start-button")
    page.wait_for_function("document.querySelectorAll('#log-output > *').length > 6")
    page.wait_for_timeout(600)
    page.screenshot(path=str(out / "syncing.png"))

    page.wait_for_function("document.querySelector('#status-panel')?.dataset.state === 'succeeded'", timeout=30000)
    page.wait_for_timeout(700)
    page.screenshot(path=str(out / "done.png"))
    browser.close()
    app.shutdown()


def scene_add_pair(playwright, workdir: Path, home: Path, out: Path) -> None:
    """!
    @brief Photograph the folder pair form with the remote dropdown open.
    @param playwright The Playwright instance.
    @param workdir A temporary folder for the app's data.
    @param home The folder that holds the local folders.
    @param out The folder the pictures are written to.
    """
    app = start_app(workdir / "form")
    browser, page = new_page(playwright, f"http://127.0.0.1:{app.web_server.port}")
    add_pairs(page, home)

    backups = home / "Backups"
    backups.mkdir(parents=True, exist_ok=True)
    page.click("#pair-add-button")
    page.wait_for_selector("#pair-name", state="visible")
    page.fill("#pair-name", "Backups")
    page.fill("#setup-local-path", str(backups))
    page.click(".remote-field__button")
    page.wait_for_selector(".remote-field__menu:not([hidden])")
    page.wait_for_timeout(500)
    page.screenshot(path=str(out / "add-folder-pair.png"))
    browser.close()
    app.shutdown()


def scene_expired(playwright, workdir: Path, home: Path, out: Path) -> None:
    """!
    @brief Photograph the expired-login badge with its popover open.
    @param playwright The Playwright instance.
    @param workdir A temporary folder for the app's data.
    @param home The folder that holds the local folders.
    @param out The folder the pictures are written to.
    """
    os.environ["DEMO_EXPIRED"] = "icloud"
    app = start_app(workdir / "expired")
    browser, page = new_page(playwright, f"http://127.0.0.1:{app.web_server.port}")
    add_pairs(page, home)
    api(page, "POST", "/api/remotes/check")
    page.wait_for_selector("#expiry:not([hidden])", timeout=15000)
    page.click("#expiry-badge")
    page.wait_for_selector("#expiry-popover:not([hidden])")
    page.wait_for_timeout(500)
    page.screenshot(path=str(out / "expired-login.png"))
    browser.close()
    app.shutdown()
    os.environ.pop("DEMO_EXPIRED", None)


def main() -> None:
    """!
    @brief Parse the command line and take all screenshots.
    """
    parser = argparse.ArgumentParser(description="Take the README screenshots.")
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "docs" / "screenshots")
    parser.add_argument("--home", type=Path, default=None)
    arguments = parser.parse_args()

    os.chmod(DEMO_RCLONE, os.stat(DEMO_RCLONE).st_mode | stat.S_IXUSR)
    arguments.out.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp())
    home = arguments.home or workdir / "you"
    try:
        with sync_playwright() as playwright:
            scene_run(playwright, workdir, home, arguments.out)
            scene_add_pair(playwright, workdir, home, arguments.out)
            scene_expired(playwright, workdir, home, arguments.out)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    print(f"Screenshots written to {arguments.out}")


if __name__ == "__main__":
    main()
