import json
import time
import random
from pathlib import Path
from typing import Optional

from playwright.sync_api import Playwright, BrowserContext, Page

from src.config import settings
from src.utils.logger import custom_print


class SessionExpired(Exception):
    pass


def launch_context(p: Playwright) -> BrowserContext:
    profile = Path(settings.PROFILE_DIR)
    first_run = not any(profile.iterdir()) if profile.exists() else True
    profile.mkdir(parents=True, exist_ok=True)
    kwargs = dict(
        user_data_dir=str(profile),
        headless=settings.HEADLESS,
        slow_mo=settings.SLOW_MO,
        viewport=settings.VIEWPORT,
        accept_downloads=True,
        args=["--disable-blink-features=AutomationControlled", "--no-first-run", "--no-default-browser-check"],
        ignore_default_args=["--enable-automation"],
    )
    ctx = None
    if settings.BROWSER_CHANNEL:
        try:
            ctx = p.chromium.launch_persistent_context(channel=settings.BROWSER_CHANNEL, **kwargs)
            custom_print("SESSION", f"Browser: {settings.BROWSER_CHANNEL} (persistent profile at {profile})")
        except Exception as e:
            custom_print("WARNING", f"Could not launch '{settings.BROWSER_CHANNEL}' ({str(e)[:120]}); falling back to bundled Chromium")
    if ctx is None:
        ctx = p.chromium.launch_persistent_context(**kwargs)
        custom_print("SESSION", f"Browser: bundled Chromium (persistent profile at {profile})")
    ctx.set_default_timeout(15000)
    ctx.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
    if first_run and Path(settings.SESSION_PATH).exists():
        try:
            cookies = json.loads(Path(settings.SESSION_PATH).read_text())
            ctx.add_cookies(cookies)
            custom_print("SESSION", f"Imported {len(cookies)} cookies from legacy {Path(settings.SESSION_PATH).name}")
        except Exception as e:
            custom_print("WARNING", f"Legacy cookie import failed: {e}")
    return ctx


def main_page(ctx: BrowserContext) -> Page:
    pages = [pg for pg in ctx.pages if not pg.is_closed()]
    page = pages[0] if pages else ctx.new_page()
    for extra in pages[1:]:
        try:
            extra.close()
        except Exception:
            pass
    return page


def save_cookies(ctx: BrowserContext):
    try:
        Path(settings.SESSION_PATH).parent.mkdir(parents=True, exist_ok=True)
        Path(settings.SESSION_PATH).write_text(json.dumps(ctx.cookies(), indent=1))
    except Exception as e:
        custom_print("WARNING", f"Could not save cookies: {e}")


# classic header (.global-nav__me, still on /jobs/search) and the newer header (primary-nav, on /feed and /jobs);
# Messaging/Notifications links only exist when logged in
LOGGED_IN_JS = r"""() => {
    const t = (document.body.innerText || '').slice(0, 800);
    const guest = /\bJoin now\b/.test(t) && /\bSign in\b/.test(t);
    const me = !!document.querySelector('.global-nav__me, img.global-nav__me-photo, [data-testid="primary-nav"], [data-view-name*="identity"], [data-view-name="navigation-settings"], a[href*="linkedin.com/messaging/"], a[href*="linkedin.com/notifications/"]');
    return {me, guest};
}"""
_cookie_fallback_warned = False


def linkedin_logged_in(page: Page) -> bool:
    global _cookie_fallback_warned
    url = page.url or ""
    if any(x in url for x in ("/authwall", "/login", "/checkpoint", "/uas/login", "signup")):
        return False
    try:
        s = page.evaluate(LOGGED_IN_JS)
    except Exception:
        return False
    if s["me"]:
        return True
    if s["guest"]:
        return False
    # no header recognised (page still loading, or LinkedIn changed its markup): fall back to the auth cookie
    try:
        has_cookie = any(c["name"] == "li_at" for c in page.context.cookies("https://www.linkedin.com"))
    except Exception:
        has_cookie = False
    if has_cookie and not _cookie_fallback_warned:
        _cookie_fallback_warned = True
        custom_print("WARNING", f"LinkedIn header not recognised on {url[:80]}; trusting the login cookie. If runs misbehave: python src/main.py capture")
    return has_cookie


def ensure_linkedin(page: Page):
    if "linkedin.com" not in (page.url or ""):
        page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
        time.sleep(2.5)
    if not linkedin_logged_in(page):
        raise SessionExpired("LinkedIn session missing or expired - run: python src/main.py setup")


def human_pause(lo: float, hi: float):
    time.sleep(random.uniform(lo, hi))


def human_scroll(page: Page, steps: int = 3):
    for _ in range(steps):
        try:
            page.mouse.wheel(0, random.randint(300, 900))
        except Exception:
            pass
        time.sleep(random.uniform(0.6, 1.6))
