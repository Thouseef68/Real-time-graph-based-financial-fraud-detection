"""Playwright automation script for Phase 11: Live Demo Studio.

Walks through the entire 7-Act "Four-Account Mule Ring" story,
interacts with the real engine pipeline, tests the interactive
mini-bank app, and saves high-resolution screenshots per act to
docs/demo_screenshots/.
"""

import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "docs" / "demo_screenshots"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

ACT_NAMES = {
    1: "act1_normal_traffic",
    2: "act2_ring_wakes_up",
    3: "act3_victims_pay",
    4: "act4_layering",
    5: "act5_detection",
    6: "act6_containment",
    7: "act7_cashout_declined",
}


def post_api(path: str, data: dict):
    url = f"http://localhost:8000{path}"
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def run_story_capture():
    print(f"[*] Starting Phase 11 Demo Story capture at 1440x900...", flush=True)
    print(f"[*] Output directory: {OUTPUT_DIR}", flush=True)

    # 1. Reset backend to Seed 42 with Protection ON
    print("[*] Resetting demo state to seed 42 with Protection ON...", flush=True)
    post_api("/api/v1/demo/runs", {"seed": 42, "speed": 1.0, "protection_enabled": True})

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            color_scheme="dark",
        )
        page = context.new_page()

        print("[*] Navigating to http://localhost:5173/ ...", flush=True)
        page.goto("http://localhost:5173/", wait_until="domcontentloaded", timeout=15000)
        time.sleep(2.0)

        # Ensure dark mode class is applied
        page.evaluate("document.documentElement.classList.add('dark')")
        time.sleep(0.5)

        # Capture Act 1 initial view
        print(f"  -> Capturing Act 1: Normal Traffic...", flush=True)
        act1_path = OUTPUT_DIR / f"{ACT_NAMES[1]}.png"
        page.screenshot(path=str(act1_path), full_page=False)
        print(f"     Saved {act1_path.name}", flush=True)

        # Advance through acts 2 to 7
        for target_act in range(2, 8):
            print(f"  -> Advancing to Act {target_act}...", flush=True)
            # Step until the backend reaches target_act
            for _ in range(40):
                status = post_api("/api/v1/demo/control", {"action": "step"})
                if status["current_act"] >= target_act:
                    break
                time.sleep(0.05)

            # Let UI update via SSE / React state
            time.sleep(1.5)

            # Switch tabs to showcase engine depth for specific acts
            try:
                if target_act == 3:
                    # Switch to redis tab for fan-in climb
                    page.locator("button", has_text="redis").click(timeout=1000)
                elif target_act == 4:
                    # Switch to kafka tab for layering chain
                    page.locator("button", has_text="kafka").click(timeout=1000)
                elif target_act == 5:
                    # Switch to decision tab for model score and SHAP reasons
                    page.locator("button", has_text="decision").click(timeout=1000)
                elif target_act == 6:
                    # Switch to cypher tab for graph containment query
                    page.locator("button", has_text="cypher").click(timeout=1000)
                elif target_act == 7:
                    # Switch back to decision tab for instant pre-check decline
                    page.locator("button", has_text="decision").click(timeout=1000)
            except Exception as e:
                print(f"     Notice switching tab: {e}", flush=True)

            time.sleep(0.8)
            act_path = OUTPUT_DIR / f"{ACT_NAMES[target_act]}.png"
            page.screenshot(path=str(act_path), full_page=False)
            print(f"     Saved {act_path.name}", flush=True)

        # Act 8: Try It Yourself Mini Bank App Modal
        print("  -> Interacting with 'Try It Yourself' transfer modal...", flush=True)
        try:
            # Click "Try It Yourself" button
            page.locator("button", has_text="Try It Yourself").click(timeout=2000)
            time.sleep(1.0)

            # Fill in transfer form: Member A trying to send 15,000 to Crypto Exchange
            page.locator("select").nth(0).select_option("CUST_MULE_A")
            page.locator("select").nth(1).select_option("MERCHANT_CRYPTO_EXCHANGE")
            page.locator("input[type='number']").fill("15000")
            time.sleep(0.5)

            # Click Submit
            page.locator("button", has_text="Execute Real Transfer").click(timeout=2000)
            time.sleep(1.5)

            # Screenshot modal result
            try_path = OUTPUT_DIR / "act8_try_it_yourself.png"
            page.screenshot(path=str(try_path), full_page=False)
            print(f"     Saved {try_path.name}", flush=True)

            # Close modal
            page.locator("button", has_text="✕").click(timeout=2000)
            time.sleep(0.5)
        except Exception as e:
            print(f"     Notice Try It Yourself: {e}", flush=True)

        # Act 9: Protection Comparison Summary (showing the side-by-side card)
        print("  -> Capturing Side-by-side Protection Comparison...", flush=True)
        try:
            time.sleep(1.0)
            comp_path = OUTPUT_DIR / "act9_protection_comparison.png"
            page.screenshot(path=str(comp_path), full_page=False)
            print(f"     Saved {comp_path.name}", flush=True)
        except Exception as e:
            print(f"     Notice Protection Comparison: {e}", flush=True)

        context.close()
        browser.close()

    print("[*] All Phase 11 Demo Screenshots captured successfully!", flush=True)


if __name__ == "__main__":
    run_story_capture()
