import time
import os
import json
import random
import argparse
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains

import config


def _within_schedule_window(now: datetime) -> bool:
    start_ok = now.hour >= config.SCHEDULE_START_HOUR
    end_ok = now.hour < config.SCHEDULE_END_HOUR
    return start_ok and end_ok


def _build_driver() -> webdriver.Chrome:
    options = Options()
    if getattr(config, "HEADLESS", False):
        options.add_argument("--headless=new")
    options.add_argument(f"--user-data-dir={config.CHROME_PROFILE_PATH}")
    options.add_argument(f"--window-size={config.VIEWPORT_WIDTH},{config.VIEWPORT_HEIGHT}")
    options.add_argument("--disable-notifications")
    options.add_argument("--lang=en-US")

    service = Service(config.CHROME_DRIVER_PATH)
    return webdriver.Chrome(service=service, options=options)


def _state_file_path() -> str:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(base_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "state.json")


def _load_state() -> dict:
    path = _state_file_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    path = _state_file_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _enforce_cooldown(now: datetime) -> None:
    cooldown_minutes = int(getattr(config, "COOLDOWN_MINUTES", 0) or 0)
    if cooldown_minutes <= 0:
        return

    state = _load_state()
    last_run_iso = state.get("last_run_start")
    if not last_run_iso:
        return

    try:
        last_run = datetime.fromisoformat(last_run_iso)
    except Exception:
        return

    delta_minutes = (now - last_run).total_seconds() / 60
    if delta_minutes < cooldown_minutes:
        remaining = int(cooldown_minutes - delta_minutes)
        raise SystemExit(f"Cooldown active. Try again in ~{remaining} minutes.")


def _dismiss_popups_best_effort(driver: webdriver.Chrome) -> None:
    """Best-effort dismissal of common modal dialogs.

    This intentionally does NOT perform any engagement action (like/follow).
    It only attempts to close obstructive UI elements like cookie banners
    and notification prompts.
    """

    candidates = [
        "Not Now",
        "Not now",
        "Allow all cookies",
        "Accept",
        "Only allow essential cookies",
        "Decline optional cookies",
        "Close",
    ]

    try:
        buttons = driver.find_elements(By.XPATH, "//button")
    except Exception:
        return

    for b in buttons:
        try:
            text = (b.text or "").strip()
            if text in candidates:
                b.click()
                time.sleep(0.5)
        except Exception:
            continue


def _random_mouse_movement(driver: webdriver.Chrome) -> None:
    """Move mouse randomly within viewport to simulate human activity."""
    if not getattr(config, "DEMO_MOUSE_MOVEMENT", False):
        return
    
    try:
        actions = ActionChains(driver)
        viewport_width = getattr(config, "VIEWPORT_WIDTH", 1280)
        viewport_height = getattr(config, "VIEWPORT_HEIGHT", 800)
        
        # Generate random coordinates within viewport
        x = random.randint(100, viewport_width - 100)
        y = random.randint(100, viewport_height - 100)
        
        # Move mouse to random position
        actions.move_by_offset(x - viewport_width//2, y - viewport_height//2).perform()
        time.sleep(0.1)
        
        # Reset mouse position to center
        actions.move_by_offset(-(x - viewport_width//2), -(y - viewport_height//2)).perform()
    except Exception:
        pass


def _demo_scroll_and_movement(driver: webdriver.Chrome, duration_seconds: int) -> None:
    """Visual demo mode: scroll and move mouse without any engagement actions."""
    print(f"DEMO MODE: Running visual demo for {duration_seconds} seconds...")
    print("This demo only shows scrolling and mouse movement - NO engagement actions.")
    
    start_time = time.time()
    
    while time.time() - start_time < duration_seconds:
        # Random scroll
        try:
            scroll_distance = random.randint(200, 600)
            driver.execute_script(f"window.scrollBy(0, {scroll_distance});")
            print(f"Demo: Scrolled down {scroll_distance}px")
        except Exception:
            pass
        
        # Random mouse movement
        _random_mouse_movement(driver)
        
        # Random wait between actions
        wait_time = random.randint(
            getattr(config, "DEMO_SCROLL_MIN_WAIT", 2),
            getattr(config, "DEMO_SCROLL_MAX_WAIT", 5)
        )
        time.sleep(wait_time)
        
        # Occasionally scroll back up a bit to simulate natural browsing
        if random.random() < 0.3:  # 30% chance
            try:
                scroll_up = random.randint(100, 300)
                driver.execute_script(f"window.scrollBy(0, -{scroll_up});")
                print(f"Demo: Scrolled up {scroll_up}px")
            except Exception:
                pass
    
    print("DEMO MODE: Visual demo completed.")


def main() -> None:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Open Instagram for login/profile setup (bypasses schedule + cooldown).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass schedule window check for this run (still no auto-engagement).",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run visual demo mode: scrolling + mouse movement (no engagement, 2 minutes).",
    )
    args = parser.parse_args()

    now = datetime.now()
    if not args.setup and not args.demo:
        if not args.force and not _within_schedule_window(now):
            raise SystemExit(
                f"Outside schedule window. Now={now.strftime('%H:%M')}, allowed={config.SCHEDULE_START_HOUR}:00-{config.SCHEDULE_END_HOUR}:00"
            )
        _enforce_cooldown(now)

    driver = _build_driver()
    start = time.time()

    if not args.setup:
        state = _load_state()
        state["last_run_start"] = now.isoformat(timespec="seconds")
        _save_state(state)

    try:
        driver.get(config.INSTAGRAM_URL)

        if args.setup:
            print("SETUP MODE: Instagram opened. Please log in to persist the session in this Chrome profile.")
            print("When you are done, close the browser window to exit (or press Ctrl+C here).")
            while True:
                try:
                    if not driver.window_handles:
                        break
                except Exception:
                    break
                _dismiss_popups_best_effort(driver)
                time.sleep(2)
            return

        if args.demo:
            print("DEMO MODE: Instagram opened for visual demonstration.")
            print("No engagement actions will be performed.")
            _dismiss_popups_best_effort(driver)
            demo_duration = getattr(config, "DEMO_DURATION_SECONDS", 120)
            _demo_scroll_and_movement(driver, demo_duration)
            print("Demo completed. Browser will remain open for you to explore manually.")
            input("Press Enter to close the browser and exit...")
            return

        print("Instagram opened. Please log in (first run) and engage manually (like/follow) for the session duration.")
        print(f"Session duration: {config.SESSION_DURATION_SECONDS // 60} minutes")

        cadence_min = int(getattr(config, "CADENCE_MIN_SECONDS", 0) or 0)
        cadence_max = int(getattr(config, "CADENCE_MAX_SECONDS", 0) or 0)
        cadence_enabled = cadence_min > 0 and cadence_max >= cadence_min
        next_prompt_at = time.time() + (random.randint(cadence_min, cadence_max) if cadence_enabled else 10**9)

        while True:
            elapsed = time.time() - start
            if elapsed >= config.SESSION_DURATION_SECONDS:
                break
            remaining = int(config.SESSION_DURATION_SECONDS - elapsed)
            if remaining % 300 == 0:
                print(f"Time remaining: {remaining // 60} minutes")

            if time.time() >= next_prompt_at:
                print("Cadence: consider moving to the next post now (manual).")
                next_prompt_at = time.time() + random.randint(cadence_min, cadence_max)

            if remaining % 30 == 0:
                _dismiss_popups_best_effort(driver)
            time.sleep(1)

    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()
