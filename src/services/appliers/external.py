import re
import time
import random
from typing import Dict, Optional

from playwright.sync_api import Page

from src.config import settings
from src.services.form_engine.engine import FormEngine, Snapshot
from src.services.appliers.base import FormRunner, ApplyResult
from src.utils.logger import custom_print

ATS_URL = [
    ("greenhouse", r"greenhouse\.io|gh_jid="),
    ("lever", r"jobs\.lever\.co|lever\.co/"),
    ("ashby", r"ashbyhq\.com"),
    ("workday", r"myworkdayjobs\.com|myworkdaysite\.com|\.workday\.com"),
    ("smartrecruiters", r"smartrecruiters\.com"),
    ("workable", r"workable\.com"),
    ("jobadder", r"jobadder\.com"),
    ("pageup", r"pageuppeople\.com|pageup\.com"),
    ("bamboohr", r"bamboohr\.com"),
    ("seek", r"seek\.(co\.nz|com\.au)"),
    ("icims", r"icims\.com"),
    ("successfactors", r"successfactors|sapsf\.|jobs\.sap\.com"),
    ("taleo", r"taleo\.net"),
    ("jobvite", r"jobvite\.com"),
    ("teamtailor", r"teamtailor\.com"),
    ("recruitee", r"recruitee\.com"),
    ("breezy", r"breezy\.hr"),
    ("livehire", r"livehire\.com"),
    ("snaphire", r"snaphire\.com"),
    ("applynow", r"applynow\.net\.au"),
]

FINGERPRINT_JS = """
() => {
  const srcs = [...document.querySelectorAll('script[src], iframe[src], link[href]')].map(e => e.getAttribute('src') || e.getAttribute('href') || '').join(' ');
  const meta = [...document.querySelectorAll('meta[name="generator"], meta[property="og:site_name"]')].map(m => m.content).join(' ');
  return (srcs + ' ' + meta + ' ' + (document.querySelector('#grnhse_app, #grnhse_iframe') ? 'greenhouse.io' : '')).slice(0, 20000);
}
"""

GUEST_RE = re.compile(r"(continue|apply|proceed) (as (a )?guest|without (an )?account|without (signing|logging) in)|^guest\b|skip (sign ?in|log ?in)", re.I)

ROOTS = {
    "greenhouse": "#application-form, form#application_form, #application, form[action*='greenhouse'], main",
    "lever": "form#application-form, .application-form, form",
    # Oct 2026: no <form>; fields and the Submit button share div#form inside the right pane
    "ashby": "#form[role='tabpanel'], .ashby-job-posting-right-pane, form, [class*='application-form'], main",
    "workday": "[data-automation-id='applyFlowPage'], [data-automation-id='applicationPage'], main, [role='main']",
    "smartrecruiters": "oc-oneclick-form, form, main",
    "workable": "form, main",
}


def detect_ats(url: str, page: Optional[Page] = None) -> str:
    for name, rx in ATS_URL:
        if re.search(rx, url or "", re.I):
            return name
    if page is not None:
        try:
            fp = page.evaluate(FINGERPRINT_JS)
            for name, rx in ATS_URL:
                if re.search(rx, fp, re.I):
                    return name
        except Exception:
            pass
    return "generic"


class ExternalApplier:
    def __init__(self, runner: FormRunner = None):
        self.runner = runner or FormRunner()

    def apply(self, page: Page, job: Dict, url: Optional[str] = None) -> ApplyResult:
        if url:
            page.goto(url, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("domcontentloaded", timeout=20000)
        except Exception:
            pass
        time.sleep(random.uniform(2.0, 3.5))
        ats = detect_ats(page.url, page)
        custom_print("APPLYING", f"Application system: {ats} ({page.url[:100]})")
        time.sleep(random.uniform(settings.EXTERNAL_READ_TIME_MIN, settings.EXTERNAL_READ_TIME_MAX))
        prep = getattr(self, f"_prep_{ats}", self._prep_generic)
        try:
            pre = prep(page, job)
        except Exception as e:
            custom_print("WARNING", f"{ats} preparation step failed: {str(e)[:150]}")
            pre = None
        if isinstance(pre, ApplyResult):
            pre.channel, pre.external_url = ats, page.url
            result = pre
        else:
            auto = settings.EXTERNAL_AUTO_SUBMIT.get(ats, False)
            hook = getattr(self, f"_hook_{ats}", self._hook_generic)
            result = self.runner.run(page, job, ats, root_selector=ROOTS.get(ats), auto_submit=auto, before_step=lambda e, s: hook(page, job, e, s))
            result.external_url = result.external_url or page.url
        if result.status in ("manual_review_needed", "error"):
            from src.services.appliers.linkedin import save_debug
            save_debug(page, job, f"{ats}: {result.error or ''}")
        return result

    def _has_form(self, snap: Snapshot) -> bool:
        real = [f for f in snap.fields if f.kind != "text" or not re.search(r"search|keyword", f.text, re.I)]
        return len(real) >= 2 or any(f.kind == "file" for f in real)

    def _click_apply(self, page: Page, eng: FormEngine, snap: Snapshot) -> Optional[Page]:
        ctx = page.context
        before = set(id(p) for p in ctx.pages)
        b = snap.button("apply")
        if b is None:
            b = next((x for x in snap.buttons if re.search(r"\bapply\b|i'?m interested|start (your )?application", x.text, re.I) and not re.search(r"linkedin|indeed|seek|with ", x.text, re.I)), None)
        if b is None:
            return None
        eng.click(b, wait=2.5)
        new = [p for p in ctx.pages if id(p) not in before and not p.is_closed()]
        return new[-1] if new else page

    def _prep_generic(self, page: Page, job: Dict) -> Optional[ApplyResult]:
        for _ in range(3):
            eng = FormEngine(page)
            snap = eng.scan()
            if self._take_guest_path(eng, snap):
                continue
            if self._has_form(snap) or snap.success:
                return None
            if self._needs_login(page):
                return self._login_gate(page, "generic")
            nxt = self._click_apply(page, eng, snap)
            if nxt is None:
                return None
            if nxt is not page:
                custom_print("WARNING", "Application opened another tab - continuing there")
                page.goto(nxt.url, wait_until="domcontentloaded")
                nxt.close()
            time.sleep(2)
        return None

    def _needs_login(self, page: Page) -> bool:
        try:
            return page.evaluate("""() => { const pw = [...document.querySelectorAll('input[type=password]')].filter(e => e.getBoundingClientRect().width > 0);
                return pw.length > 0 && /sign in|log in|login|create (an )?account|password/i.test(document.body.innerText.slice(0, 3000)); }""")
        except Exception:
            return False

    def _login_gate(self, page: Page, ats: str) -> Optional[ApplyResult]:
        if self.runner.human_gate(f"{ats}: sign in or create an account in the browser (your profile keeps the login)"):
            time.sleep(2)
            return None
        return ApplyResult("manual_review_needed", f"{ats} requires sign-in / account", 0, ats)

    def _take_guest_path(self, eng: FormEngine, snap: Snapshot) -> bool:
        """Sites offering sign-in or a guest route always get the guest route (social sign-in is never clicked)."""
        b = next((b for b in snap.buttons if GUEST_RE.search(b.text or "")), None)
        if not b:
            return False
        custom_print("APPLYING", f"Taking the guest route: '{b.text[:40]}'")
        eng.click(b)
        time.sleep(2)
        return True

    def _hook_generic(self, page: Page, job: Dict, eng: FormEngine, snap: Snapshot) -> Optional[ApplyResult]:
        if self._take_guest_path(eng, snap):
            return None
        if not snap.fields and self._needs_login(page):
            return self._login_gate(page, "site")
        return None

    def _prep_greenhouse(self, page: Page, job: Dict) -> Optional[ApplyResult]:
        eng = FormEngine(page)
        snap = eng.scan()
        if not self._has_form(snap):
            b = snap.button("apply") or next((x for x in snap.buttons if re.fullmatch(r"apply( for this job)?( now)?", x.text.strip(), re.I)), None)
            if b:
                eng.click(b, wait=2)
        return None

    def _prep_lever(self, page: Page, job: Dict) -> Optional[ApplyResult]:
        if re.search(r"jobs\.lever\.co/[^/]+/[0-9a-f-]{36}/?$", page.url):
            page.goto(page.url.rstrip("/") + "/apply", wait_until="domcontentloaded")
            time.sleep(2)
        return None

    def _prep_ashby(self, page: Page, job: Dict) -> Optional[ApplyResult]:
        if "/application" not in page.url:
            m = re.search(r"(https://jobs\.ashbyhq\.com/[^/]+/[0-9a-f-]{36})", page.url)
            if m:
                page.goto(m.group(1) + "/application", wait_until="domcontentloaded")
                time.sleep(2.5)
            else:
                FormEngine(page).click_text(r"^application$|apply for this job", roles=("tab", "button", "link"))
                time.sleep(2)
        return None

    def _prep_workday(self, page: Page, job: Dict) -> Optional[ApplyResult]:
        eng = FormEngine(page)
        if page.locator('[data-automation-id="adventureButton"], a[data-automation-id="adventureButton"]').count():
            page.locator('[data-automation-id="adventureButton"]').first.click()
            time.sleep(2.5)
        for label in (r"use my last application", r"apply manually"):
            if eng.click_text(label, roles=("button", "link")):
                time.sleep(3)
                break
        return self._workday_signin(page)

    def _workday_signin(self, page: Page) -> Optional[ApplyResult]:
        email = settings.env("ATS_ACCOUNT_EMAIL")
        password = settings.env("ATS_ACCOUNT_PASSWORD")
        for _ in range(2):
            time.sleep(1.5)
            em = page.locator('[data-automation-id="email"], input[type="email"]').first
            pw = page.locator('[data-automation-id="password"], input[type="password"]').first
            if not (em.count() and pw.count() and pw.is_visible()):
                return None
            if not (email and password):
                return self._login_gate(page, "workday")
            em.fill(email)
            pw.fill(password)
            verify = page.locator('[data-automation-id="verifyPassword"]').first
            if verify.count() and verify.is_visible():
                verify.fill(password)
                cb = page.locator('[data-automation-id="createAccountCheckbox"]').first
                if cb.count() and not cb.is_checked():
                    cb.check()
                page.locator('[data-automation-id="createAccountSubmitButton"], button:has-text("Create Account")').first.click()
            else:
                page.locator('[data-automation-id="signInSubmitButton"], button:has-text("Sign In")').first.click()
            time.sleep(4)
            body = page.evaluate("() => document.body.innerText.slice(0, 3000)")
            if re.search(r"verify your (email|account)|verification email|check your email", body, re.I):
                return self._login_gate(page, "workday (verify the email Workday just sent)")
            if re.search(r"wrong email or password|invalid (credentials|username)|account (does not|doesn't) exist|no account", body, re.I):
                if FormEngine(page).click_text(r"create account", roles=("button", "link")):
                    time.sleep(2.5)
                    continue
                return self._login_gate(page, "workday")
            if not page.locator('[data-automation-id="password"]').first.is_visible():
                return None
        return self._login_gate(page, "workday")

    def _hook_workday(self, page: Page, job: Dict, eng: FormEngine, snap: Snapshot) -> Optional[ApplyResult]:
        if self._needs_login(page):
            r = self._workday_signin(page)
            if r:
                return r
        nxt = page.locator('[data-automation-id="pageFooterNextButton"], [data-automation-id="bottom-navigation-next-button"]').first
        if nxt.count() and nxt.is_visible() and not snap.button("next", "review", "submit"):
            try:
                txt = nxt.inner_text()
                if re.search(r"submit", txt, re.I):
                    return None
                nxt.click()
                time.sleep(3)
            except Exception:
                pass
        return None

    def _prep_seek(self, page: Page, job: Dict) -> Optional[ApplyResult]:
        if self._needs_login(page) or re.search(r"sign in", page.url, re.I):
            return self._login_gate(page, "SEEK")
        eng = FormEngine(page)
        snap = eng.scan()
        if not self._has_form(snap):
            eng.click_text(r"^(quick )?apply$", roles=("link", "button"))
            time.sleep(3)
        if self._needs_login(page):
            return self._login_gate(page, "SEEK")
        return None
