import json
import os
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, BrowserContext, Page

from src.utils.logger import custom_print

class SessionManager:
    def __init__(self, session_path: str):
        self.session_path = session_path

    def session_exists(self) -> bool:
        return os.path.exists(self.session_path)

    def save_session(self) -> None:
        custom_print("SESSION", "=" * 60)
        custom_print("SESSION", "LINKEDIN SESSION SETUP")
        custom_print("SESSION", "=" * 60)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            context = browser.new_context()
            page = context.new_page()

            page.goto("https://www.linkedin.com/login")

            custom_print("SESSION", "Please login to LinkedIn manually in the browser window")
            custom_print("SESSION", "Complete any 2FA if prompted")
            custom_print("SESSION", "Wait until you can see your LinkedIn feed")
            custom_print("SESSION", "=" * 60)
            input("\nPress ENTER after you've logged in and can see your feed...")

            page.wait_for_timeout(2000)

            try:
                if "feed" not in page.url and "mynetwork" not in page.url:
                    custom_print("WARNING", "Warning: You might not be logged in properly.")
                    custom_print("WARNING", f"Current URL: {page.url}")
                    proceed = input("Continue anyway? (y/n): ")
                    if proceed.lower() != 'y':
                        browser.close()
                        return
            except Exception as e:
                custom_print("WARNING", f"Could not verify login: {e}")

            cookies = context.cookies()
            Path(self.session_path).parent.mkdir(parents=True, exist_ok=True)
            with open(self.session_path, 'w') as f:
                json.dump(cookies, f, indent=2)

            custom_print("SUCCESS", f"Session saved to {self.session_path}")
            custom_print("INFO", "You can now run: python src/main.py run")
            browser.close()

    def load_session(self, context: BrowserContext):
        if not os.path.exists(self.session_path):
            raise FileNotFoundError(
                f"Session file not found: {self.session_path}\n"
                "Run 'python src/main.py setup' first to save your session"
            )

        with open(self.session_path, 'r') as f:
            cookies = json.load(f)
        context.add_cookies(cookies)
        custom_print("SUCCESS", f"Loaded session from {self.session_path}")

    def recycle_page(self, context: BrowserContext, old_page: Page) -> Page:

        custom_print("INFO", "♻️  Recycling browser page to prevent memory crash...")
        try:
            old_page.close()
        except Exception:
            pass

        new_page = context.new_page()
        time.sleep(1)
        return new_page