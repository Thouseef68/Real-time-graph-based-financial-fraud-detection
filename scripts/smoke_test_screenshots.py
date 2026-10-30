"""Playwright Smoke Test & UI Screenshot Generator.

Automates smoke testing across all core application pages at 1440x900 resolution
in both light and dark color schemes, saving artifacts to docs/screenshots/.
"""

import os
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

OUTPUT_DIR = Path("docs/screenshots")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PAGES = [
    ("overview", "http://localhost:5173/overview"),
    ("live_alerts", "http://localhost:5173/alerts"),
    ("network_explorer", "http://localhost:5173/graph"),
    ("model_performance", "http://localhost:5173/models"),
    ("monitoring", "http://localhost:5173/monitoring"),
    ("simulator", "http://localhost:5173/simulator"),
    ("audit_chain", "http://localhost:5173/audit"),
    ("settings", "http://localhost:5173/settings"),
]


def capture_screenshots():
    print(f"Starting Playwright smoke test at 1440x900 across {len(PAGES)} pages...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        for mode in ["dark", "light"]:
            context = browser.new_context(
                viewport={"width": 1440, "height": 900},
                color_scheme=mode,
            )
            page = context.new_page()

            for name, url in PAGES:
                print(f"  -> Testing [{mode}] {name}: {url}")
                for attempt in range(3):
                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=15000)
                        break
                    except Exception as e:
                        if attempt == 2:
                            raise e
                        time.sleep(1.0)
                time.sleep(1.5)  # Allow React render and animations

                # Toggle dark class on root html if needed
                if mode == "dark":
                    page.evaluate("document.documentElement.classList.add('dark')")
                else:
                    page.evaluate("document.documentElement.classList.remove('dark')")
                time.sleep(0.3)

                screenshot_path = OUTPUT_DIR / f"{name}_{mode}_1440px.png"
                page.screenshot(path=str(screenshot_path), full_page=False)
                print(f"     Saved {screenshot_path}")

            context.close()

        browser.close()
    print("Smoke test and screenshot capture complete!")


if __name__ == "__main__":
    capture_screenshots()
