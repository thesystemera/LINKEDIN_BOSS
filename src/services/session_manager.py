import time
from playwright.sync_api import sync_playwright, BrowserContext, Page

from src.config import settings
from src.services.browser import launch_context, main_page, save_cookies, linkedin_logged_in
from src.utils.logger import custom_print


class SessionManager:
    def __init__(self, session_path: str = None):
        self.session_path = session_path or settings.SESSION_PATH

    def session_exists(self) -> bool:
        profile = settings.PROFILE_DIR
        has_profile = profile.exists() and any(profile.iterdir())
        from pathlib import Path
        return has_profile or Path(self.session_path).exists()

    def save_session(self) -> None:
        custom_print("SESSION", "=" * 60)
        custom_print("SESSION", "LINKEDIN + APPLICATION SITES LOGIN")
        custom_print("SESSION", "=" * 60)
        with sync_playwright() as p:
            ctx = launch_context(p)
            page = main_page(ctx)
            page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
            custom_print("SESSION", "Log in to LinkedIn in the browser window (complete any 2FA).")
            custom_print("SESSION", "Optional: in new tabs, also sign in to SEEK / Workday portals you use - the profile keeps those logins.")
            input("\nPress ENTER once you can see your LinkedIn feed...")
            page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
            time.sleep(3)
            if not linkedin_logged_in(page):
                custom_print("WARNING", f"Login not detected (url: {page.url}). The profile is saved anyway; re-run setup if runs fail.")
            else:
                custom_print("SUCCESS", "LinkedIn login detected")
            save_cookies(ctx)
            ctx.close()
        custom_print("SUCCESS", f"Browser profile saved to {settings.PROFILE_DIR}")

    def load_session(self, context: BrowserContext):
        return None

    def recycle_page(self, context: BrowserContext, old_page: Page) -> Page:
        custom_print("INFO", "♻️  Recycling browser page")
        new_page = context.new_page()
        try:
            old_page.close()
        except Exception:
            pass
        time.sleep(1)
        return new_page
