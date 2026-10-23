import re
import time
import random
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from playwright.sync_api import Page

from src.config import settings
from src.services.browser import SessionExpired, linkedin_logged_in, human_scroll
from src.services.documents import file_purpose
from src.services.cv_data import APPLICATION_PROFILE
from src.services.form_engine.engine import FormEngine, Snapshot
from src.services.appliers.base import FormRunner, ApplyResult
from src.utils.logger import custom_print

# Oct 2026: Easy Apply is a native <dialog open data-testid="dialog"> in the main frame (no role/aria-modal attributes)
LI_ROOT = '.jobs-easy-apply-modal, [data-test-modal-id="easy-apply-modal"], dialog[open], [data-testid="dialog"], div[role="dialog"][aria-labelledby*="apply"], div[role="dialog"], [aria-modal="true"], [data-view-name*="apply-flow"], [data-view-name*="easy-apply"], main form'

JOB_STATE_JS = """
() => {
  const clean = s => (s || '').replace(/\\s+/g, ' ').trim();
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(e).visibility !== 'hidden'; };
  const top = document.querySelector('.jobs-details__main-content, .jobs-search__job-details--container, .job-view-layout, [data-view-name="job-details"], main') || document.body;
  const full = clean(top.innerText).slice(0, 8000);
  const cut = full.search(/About the job/i);
  const t = cut > 0 ? full.slice(0, cut) : full.slice(0, 1500);
  const ctrls = [...document.querySelectorAll('button, a')].filter(vis).map(e => ({ text: clean(e.innerText), aria: clean(e.getAttribute('aria-label')), dv: e.getAttribute('data-view-name') || '' }));
  const isApply = c => c.dv === 'job-apply-button' || /^(easy apply|apply)$/i.test(c.text) || /^(easy apply|apply) to /i.test(c.aria) || /apply on company website/i.test(c.aria + ' ' + c.text);
  const applyCtrls = ctrls.filter(isApply);
  const easy = applyCtrls.some(c => /easy apply/i.test(c.text + ' ' + c.aria));
  const ext = applyCtrls.some(c => !/easy apply/i.test(c.text + ' ' + c.aria));
  const applied = /\\bApplied \\d+ (second|minute|hour|day|week|month)s? ago\\b|\\bApplication submitted\\b|\\bYou applied on\\b/.test(t);
  const closed = /No longer accepting applications|This job is no longer available|job has expired|job post has been removed/i.test(t);
  return { easy, ext, applied, closed, controls: applyCtrls.slice(0, 4) };
}
"""

APPLY_UI_JS = """
() => {
  const clean = s => (s || '').replace(/\\s+/g, ' ').trim();
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(e).visibility !== 'hidden'; };
  const dialogs = [...document.querySelectorAll('[role="dialog"], .artdeco-modal, [aria-modal="true"], dialog[open], [data-testid="dialog"]')].filter(vis);
  const texts = dialogs.map(d => clean(d.innerText).slice(0, 400));
  const ready = dialogs.some(d => d.querySelector('input, select, textarea, [role="radio"], [role="combobox"]') && /apply|application|contact info|resume|questions|review/i.test(clean(d.innerText).slice(0, 600)))
     || /\\/apply\\/?(\\?|$)|openSDUIApplyFlow/i.test(location.href) && !!document.querySelector('main input, main select, main textarea, form input');
  const safety = texts.some(t => /job search safety|safety reminder|continue applying/i.test(t));
  const resume = texts.some(t => /continue (your )?application|resume (your )?application|pick up where/i.test(t));
  const saveDraft = texts.some(t => /save this application|discard/i.test(t)) && !ready;
  const external = texts.some(t => /apply on company website|leaving linkedin|share your profile|you('|’)re about to leave/i.test(t));
  return { ready, safety, resume, saveDraft, external, texts: texts.slice(0, 3), url: location.href };
}
"""


def save_debug(page: Page, job: Dict, context: str):
    try:
        settings.DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        company = re.sub(r"[^\w]+", "_", job.get("company", "unknown"))[:30]
        jid = re.sub(r"[^\w\-]+", "_", str(job.get('linkedin_job_id') or job.get('id') or ''))[:40]
        stem = settings.DEBUG_DIR / f"{ts}_{company}_{jid}"
        html = page.content()
        header = f"<!--\nDEBUG CAPTURE\nTimestamp: {datetime.now().isoformat()}\nJob: {job.get('title')}\nCompany: {job.get('company')}\nURL: {page.url}\nContext: {context}\n-->\n"
        Path(f"{stem}.html").write_text(header + html, encoding="utf-8")
        page.screenshot(path=f"{stem}.png", full_page=False)
        custom_print("DEBUG", f"Saved debug capture: {stem.name}.html/.png")
    except Exception as e:
        custom_print("WARNING", f"Debug capture failed: {e}")


class LinkedInApplier:
    def __init__(self, runner: FormRunner = None, external=None):
        self.runner = runner or FormRunner()
        self.external = external

    def job_state(self, page: Page) -> Dict:
        try:
            return page.evaluate(JOB_STATE_JS)
        except Exception:
            return {"easy": False, "ext": False, "applied": False, "closed": False}

    def open_job(self, page: Page, job: Dict) -> Dict:
        page.goto(job["url"], wait_until="domcontentloaded")
        time.sleep(random.uniform(2.5, 4.0))
        if not linkedin_logged_in(page):
            raise SessionExpired("LinkedIn session expired - run: python src/main.py setup")
        state = self.job_state(page)
        if not (state["easy"] or state["ext"] or state["applied"] or state["closed"]):
            time.sleep(3)
            state = self.job_state(page)
        return state

    def _apply_locator(self, page: Page, easy: bool):
        rx = re.compile(r"easy apply", re.I) if easy else re.compile(r"^\s*apply\s*$|apply on company website|^apply to ", re.I)
        cands = [page.locator('[data-view-name="job-apply-button"]'), page.get_by_role("button", name=rx), page.get_by_role("link", name=rx),
                 page.locator('.jobs-apply-button, [aria-label*="Easy Apply"]' if easy else '.jobs-apply-button, [aria-label*="company website"]')]
        for c in cands:
            try:
                n = c.count()
            except Exception:
                continue
            for i in range(n):
                el = c.nth(i)
                try:
                    if not el.is_visible():
                        continue
                    label = f"{el.inner_text()} {el.get_attribute('aria-label') or ''}"
                    if easy and not re.search(r"easy apply", label, re.I):
                        continue
                    if not easy and re.search(r"easy apply", label, re.I):
                        continue
                    return el
                except Exception:
                    continue
        return None

    def ui_state(self, page: Page) -> Dict:
        merged = {"ready": False, "safety": False, "resume": False, "saveDraft": False, "external": False, "texts": [], "frames": []}
        for fr in page.frames:
            try:
                st = fr.evaluate(APPLY_UI_JS)
            except Exception:
                continue
            for k in ("ready", "safety", "resume", "saveDraft", "external"):
                merged[k] = merged[k] or st.get(k, False)
            merged["texts"] += st.get("texts", [])
            if st.get("ready"):
                merged["frames"].append(fr.url[:80])
        merged["url"] = page.url
        return merged

    def _click_in_frames(self, page: Page, pattern: str) -> bool:
        """Click a dialog's button or link (LinkedIn's "Share your profile?" Continue is a link), else a page button."""
        rx = re.compile(pattern, re.I)
        for fr in page.frames:
            dialogs = fr.locator('dialog[open], [role="dialog"], [aria-modal="true"]')
            for loc in (dialogs.get_by_role("button", name=rx), dialogs.get_by_role("link", name=rx), fr.get_by_role("button", name=rx)):
                try:
                    for i in range(loc.count()):
                        el = loc.nth(i)
                        if el.is_visible():
                            el.click(timeout=3000)
                            return True
                except Exception:
                    continue
        return False

    def _wait_apply_ui(self, page: Page, timeout: float = 25) -> Optional[Dict]:
        end = time.time() + timeout
        st = None
        while time.time() < end:
            st = self.ui_state(page)
            if (st["safety"] or st["resume"]) and not st["ready"]:
                self._click_in_frames(page, r"continue applying|^continue$|resume|^next$")
                time.sleep(1.5)
                continue
            if st["ready"]:
                if st["frames"] and st["frames"][0] != page.url[:80]:
                    custom_print("DEBUG", f"Easy Apply form is inside a frame: {st['frames'][0]}")
                return st
            time.sleep(0.8)
        return st

    def apply(self, page: Page, job: Dict) -> ApplyResult:
        custom_print("APPLYING", f"Opening: {job['url']}")
        state = self.open_job(page, job)
        if state.get("applied"):
            return ApplyResult("already_applied", "LinkedIn shows this job as already applied", 0)
        if state.get("closed"):
            return ApplyResult("expired", "No longer accepting applications", 0)
        read = random.uniform(settings.JOB_READ_TIME_MIN, settings.JOB_READ_TIME_MAX)
        custom_print("APPLYING", f"Reading job for {read:.0f}s...")
        end = time.time() + read
        while time.time() < end:
            human_scroll(page, 1)
            time.sleep(min(max(0, end - time.time()), random.uniform(8, 20)))
        if state.get("easy"):
            return self.easy_apply(page, job)
        if state.get("ext"):
            if not settings.EXTERNAL_APPLY or not self.external:
                return ApplyResult("external", "External application (EXTERNAL_APPLY off)", 0, "external")
            return self.external_apply(page, job)
        save_debug(page, job, "No apply button found")
        return ApplyResult("no_easy_apply", "No apply button found on job page", 0)

    def fill_known_work_dates(self, engine: FormEngine, snap: Snapshot) -> bool:
        """LinkedIn opens an imported work-history entry whose dates are missing. If the candidate gave dates for that
        entry (APPLICATION_PROFILE work_history_dates), fill them, keep 'I currently work here' off, and Save the entry."""
        editor = [f for f in snap.fields if re.search(r"edit experience", f.raw.get("section") or "", re.I)]
        if not editor:
            return False
        who = " ".join(str(f.raw.get("value") or "") for f in editor if re.match(r"(your )?title|company", f.text, re.I)).lower()
        known = next((v for k, v in APPLICATION_PROFILE.get("work_history_dates", {}).items() if k.lower() in who), None)
        if not known:
            return False
        current = next((f for f in editor if re.search(r"currently work here", f.text, re.I)), None)
        if current and current.filled:
            engine.fill(current, "No")
            editor = [f for f in engine.scan().fields if re.search(r"edit experience", f.raw.get("section") or "", re.I)]
        want = {}
        for side in ("from", "to"):
            month, year = known[side].split()
            want[(side, "month")], want[(side, "year")] = month, year
        filled = []
        for f in editor:
            m = re.match(r"(from|to)\s*\((month|year)\)", f.text, re.I)
            if m and not f.filled:
                v = want[(m.group(1).lower(), m.group(2).lower())]
                if engine.fill(f, v)[0]:
                    filled.append(f"{f.text}={v}")
        save = next((b for b in engine.scan().buttons if (b.text or "").strip().lower() == "save"), None)
        if save:
            engine.click(save)
        custom_print("FORM", f"✓ [profile] work history '{who[:50]}' dates: {', '.join(filled) or 'already set'}{' (saved)' if save else ''}")
        return True

    def easy_apply(self, page: Page, job: Dict) -> ApplyResult:
        btn = self._apply_locator(page, easy=True)
        if not btn:
            save_debug(page, job, "Easy Apply button not found")
            return ApplyResult("no_easy_apply", "Easy Apply button not found", 0)
        custom_print("APPLYING", "Clicking Easy Apply...")
        btn.scroll_into_view_if_needed()
        time.sleep(random.uniform(0.5, 1.2))
        btn.click()
        st = self._wait_apply_ui(page, 20)
        if not st or not st.get("ready"):
            btn = self._apply_locator(page, easy=True)
            if btn:
                try:
                    btn.click()
                except Exception:
                    pass
            st = self._wait_apply_ui(page, 15)
        if not st or not st.get("ready"):
            save_debug(page, job, f"Easy Apply UI did not appear: {st}")
            return ApplyResult("error", f"Easy Apply UI did not appear (url={page.url[:80]})", 0)

        resume_selected = {"v": False}

        def hook(engine: FormEngine, snap: Snapshot):
            sel = False
            for fr in page.frames:
                try:
                    if fr.evaluate("() => !!document.querySelector('.jobs-document-upload-redesign-card__container--selected, [class*=\"document-upload\"][class*=\"selected\"], [aria-label=\"Selected\"][class*=\"document\"]')"):
                        sel = True
                        break
                except Exception:
                    continue
            resume_selected["v"] = sel
            for f in snap.fields:
                if f.kind == "checkbox" and re.search(r"follow .*(stay up to date|updates)|follow company", f.text, re.I) and f.filled:
                    engine.fill(f, "No")
            self.fill_known_work_dates(engine, snap)
            return None

        result = self.runner.run(page, job, "linkedin_easy", root_selector=LI_ROOT, auto_submit=True, before_step=hook, strict_root=True,
                                 skip_field=lambda f: f.kind == "file" and resume_selected["v"] and not f.required and file_purpose(f"{f.label} {f.question}") == "cv")
        if result.status in ("success", "submitted_unconfirmed"):
            time.sleep(1.5)
            self._click_in_frames(page, r"^done$|^dismiss$|^not now$")
        else:
            if result.status in ("manual_review_needed", "error"):
                save_debug(page, job, result.error or "")
            self.close_modal(page)
        return result

    def external_apply(self, page: Page, job: Dict) -> ApplyResult:
        btn = self._apply_locator(page, easy=False)
        if not btn:
            return ApplyResult("no_easy_apply", "External apply button not found", 0, "external")
        ctx = page.context
        before = set(id(p) for p in ctx.pages)
        btn.scroll_into_view_if_needed()
        time.sleep(random.uniform(0.5, 1.2))
        btn.click()
        target = None
        end = time.time() + 20
        while time.time() < end and target is None:
            time.sleep(0.8)
            new = [p for p in ctx.pages if id(p) not in before and not p.is_closed()]
            if new:
                target = new[-1]
                break
            if "linkedin.com" not in (page.url or ""):
                target = page
                break
            st = self.ui_state(page)
            if st.get("external") or st.get("safety"):
                self._click_in_frames(page, r"^continue\b(?! with)|continue to (apply|site|application)|^apply$|i understand")
        if target is None:
            save_debug(page, job, "External application did not open")
            return ApplyResult("manual_review_needed", "External application page did not open", 0, "external")
        try:
            target.wait_for_load_state("domcontentloaded", timeout=20000)
        except Exception:
            pass
        for _ in range(10):
            if "linkedin.com" not in (target.url or "") and target.url not in ("about:blank", ""):
                break
            time.sleep(1)
        url = target.url
        custom_print("APPLYING", f"External application: {url[:120]}")
        try:
            result = self.external.apply(target, job, url=None)
        finally:
            if target is not page:
                try:
                    target.close()
                except Exception:
                    pass
            else:
                try:
                    page.go_back()
                except Exception:
                    pass
        result.external_url = result.external_url or url
        return result

    def close_modal(self, page: Page):
        try:
            if self._click_in_frames(page, r"^dismiss$|^close$"):
                time.sleep(1)
                self._click_in_frames(page, r"^discard$")
                time.sleep(0.8)
        except Exception:
            pass
