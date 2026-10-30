"""Capture Phase 12 Playwright screenshots of the live money flow graph

Before and after the 3-sender fan-in pattern, saved to docs/demo_screenshots/.
"""

import os
import sys
import time
import requests
from pathlib import Path
from playwright.sync_api import sync_playwright

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

OUTPUT_DIR = Path("docs/demo_screenshots")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = "http://localhost:8000"
FRONTEND_URL = "http://localhost:5173/demo"
ROOM_CODE = "MULE42"


def setup_live_participants():
    print(f"Setting up participants for room {ROOM_CODE}...")
    # Wipe room to start fresh
    try:
        requests.delete(f"{BASE_URL}/api/v1/live/rooms/{ROOM_CODE}", timeout=5)
    except Exception:
        pass

    # Ensure room is created
    requests.post(f"{BASE_URL}/api/v1/live/rooms", json={"room_code": ROOM_CODE}, timeout=5)

    # Join 4 audience participants
    p_myphone = requests.post(f"{BASE_URL}/api/v1/live/rooms/{ROOM_CODE}/join", json={
        "display_name": "MyPhone",
        "device_id": "DEV_MYPHONE_SECURE",
        "network_label": "Campus-WiFi",
    }).json()["participant"]

    p_thouseef = requests.post(f"{BASE_URL}/api/v1/live/rooms/{ROOM_CODE}/join", json={
        "display_name": "Thouseef",
        "device_id": "DEV_THOUSEEF_LAPTOP",
        "network_label": "Campus-WiFi",
    }).json()["participant"]

    p_alice = requests.post(f"{BASE_URL}/api/v1/live/rooms/{ROOM_CODE}/join", json={
        "display_name": "Alice",
        "device_id": "DEV_ALICE_IPHONE",
        "network_label": "Campus-WiFi",
    }).json()["participant"]

    p_student = requests.post(f"{BASE_URL}/api/v1/live/rooms/{ROOM_CODE}/join", json={
        "display_name": "Student_1",
        "device_id": "DEV_STUDENT1_ANDROID",
        "network_label": "Campus-WiFi",
    }).json()["participant"]

    print("Participants registered successfully.")
    return {
        "myphone": p_myphone["account_id"],
        "thouseef": p_thouseef["account_id"],
        "alice": p_alice["account_id"],
        "student": p_student["account_id"],
    }


def execute_transfer(sender_id, receiver_id, amount, note=""):
    payload = {
        "room_code": ROOM_CODE,
        "sender_id": sender_id,
        "receiver_id": receiver_id,
        "amount": amount,
        "note": note,
        "device_id": "DEV_TEST_TRANSFER",
        "raw_ip": "192.168.1.100",
        "network_label": "Campus-WiFi",
    }
    res = requests.post(f"{BASE_URL}/api/v1/live/transfer", json=payload, timeout=5)
    return res.json()


def run_capture():
    ids = setup_live_participants()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 920},
            color_scheme="dark",
        )
        page = context.new_page()

        print(f"Navigating to {FRONTEND_URL}...")
        page.goto(FRONTEND_URL, wait_until="domcontentloaded", timeout=15000)
        time.sleep(2.0)

        # Switch to "Live Sandbox Bank" mode
        print("Switching to Live Sandbox Bank mode...")
        page.click("text=Live Sandbox Bank: Audience Participation (Real Phones)")
        time.sleep(2.0)

        # 1. Capture BEFORE pattern
        before_path = OUTPUT_DIR / "phase12_graph_before_pattern.png"
        print(f"Capturing BEFORE pattern screenshot -> {before_path}...")
        page.screenshot(path=str(before_path), full_page=False)

        # 2. Execute 3-sender fan-in pattern
        print("\n--- Executing 3-sender fan-in pattern ---")
        t1 = execute_transfer(ids["myphone"], ids["student"], 500.0, "Payment 1")
        print(f"1. MyPhone -> Student_1 (₹500): {t1.get('status')} [{t1.get('tier')}]")
        time.sleep(0.5)

        t2 = execute_transfer(ids["thouseef"], ids["student"], 500.0, "Payment 2")
        print(f"2. Thouseef -> Student_1 (₹500): {t2.get('status')} [{t2.get('tier')}]")
        time.sleep(0.5)

        t3 = execute_transfer(ids["alice"], ids["student"], 500.0, "Payment 3")
        print(f"3. Alice -> Student_1 (₹500): {t3.get('status')} [{t3.get('tier')}]")
        time.sleep(1.0)

        # Student_1 forwards most of it to crypto exchange
        t4 = execute_transfer(ids["student"], "BOT_CRYPTO_EXCHANGE", 1400.0, "Rapid cashout")
        print(f"4. Student_1 -> BOT_CRYPTO_EXCHANGE (₹1400): {t4.get('status')} [{t4.get('tier')}]")
        time.sleep(2.5)  # Allow live graph and SSE updates to render

        # 3. Capture AFTER fan-in pattern
        after_path = OUTPUT_DIR / "phase12_graph_after_fanin_pattern.png"
        print(f"Capturing AFTER fan-in pattern screenshot -> {after_path}...")
        page.screenshot(path=str(after_path), full_page=False)

        # 4. Capture full page view
        full_path = OUTPUT_DIR / "phase12_live_studio_full_view.png"
        print(f"Capturing full studio view -> {full_path}...")
        page.screenshot(path=str(full_path), full_page=True)

        browser.close()
        print("\nAll Phase 12 Playwright screenshots captured successfully!")


if __name__ == "__main__":
    run_capture()
