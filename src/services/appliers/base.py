import re
import time
import asyncio
import random
from dataclasses import dataclass, field as dc_field
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel
from playwright.sync_api import Page
from rich.table import Table
from rich import box

from src.config import settings
from src.services.ai_service import AIService
from src.services.form_engine.engine import FormEngine, Snapshot, Field
from src.services.form_engine.answerer import Answerer, Answer, PROFILE_ENTRY_RE
from src.utils.logger import custom_print, console

RISKY_BTN_RE = re.compile(r"submit|send|finish|complete|confirm|apply|discard|delete|withdraw|cancel|remove|sign ?out|log ?out|decline|google|microsoft|apple|facebook|github", re.I)
CODE_RE = re.compile(r"(verification|security|confirmation|one[- ]time|access) code|\botp\b|enter the code|code (we|that was) (sent|emailed)", re.I)


def run_async(coro):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


@dataclass
class ApplyResult:
    status: str
    error: Optional[str] = None
    steps: int = 0
    channel: str = "linkedin_easy"
    external_url: Optional[str] = None
    qa: List[Dict[str, Any]] = dc_field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {"status": self.status, "error": self.error, "steps": self.steps, "channel": self.channel,
                "external_url": self.external_url, "qa": self.qa}


class VisionStep(BaseModel):
    action: str
    target: str = ""
    value: str = ""
    reason: str = ""


class VisionAssist:
    def __init__(self):
        self.ai = AIService()

    def next_action(self, page: Page, snap: Snapshot, job: Dict, goal: str) -> Optional[Dict]:
        try:
            png = page.screenshot(full_page=False)
        except Exception:
            return None
        buttons = [{"id": b.raw["bid"], "text": b.text, "kind": b.kind, "disabled": b.disabled} for b in snap.buttons][:60]
        fields = [{"id": f.fid, "question": f.text[:160], "kind": f.kind, "value": str(f.value)[:60], "required": f.required, "errors": f.errors}
                  for f in snap.fields][:60]
        prompt = f"""You are operating a web browser to {goal} for: {job.get('title')} at {job.get('company')}.
The screenshot shows the current page. Below are the clickable buttons and form fields detected on it (ids are stable for this step).
Choose ONE next action to make progress toward submitting the application:
- "click" with target = a button id
- "fill" with target = a field id and value = what to enter (only if you are sure)
- "human" if a login, account creation, captcha, email code or unusual decision is needed
- "done" if the application has clearly been submitted
- "stuck" if nothing sensible is possible
Never click buttons that withdraw, delete, sign out, or navigate to unrelated pages.

Errors on page: {snap.errors[:6]}
Headings: {snap.headings}
BUTTONS: {buttons}
FIELDS: {fields}
"""
        try:
            return run_async(self.ai.structured(prompt, VisionStep, role="vision", images=[png]))
        except Exception as e:
            custom_print("WARNING", f"Vision assist failed: {str(e)[:120]}")
            return None


class FormRunner:
    def __init__(self, answerer: Answerer = None, vision: VisionAssist = None):
        self.answerer = answerer or Answerer()
        self.vision = vision or (VisionAssist() if settings.VISION_ASSIST else None)

    def human_gate(self, message: str) -> bool:
        if not settings.MANUAL_APPROVAL:
            custom_print("WARNING", f"Needs you: {message} (auto mode - skipping)")
            return False
        console.print(f"\n[bold yellow]ACTION NEEDED:[/bold yellow] {message}")
        r = input("Do it in the browser, then press ENTER to continue (or 's' to skip this job): ").strip().lower()
        return r != "s"

    def print_summary(self, job: Dict, qa: Dict[str, Dict]):
        t = Table(title=f"{job.get('title', '')[:60]} @ {job.get('company', '')[:40]}", box=box.SIMPLE_HEAVY, show_lines=False)
        t.add_column("Question", style="cyan", max_width=60)
        t.add_column("Answer", style="white", max_width=70)
        t.add_column("Source", style="magenta")
        t.add_column("", style="red")
        for row in qa.values():
            t.add_row(row["question"][:160], str(row["answer"])[:220], row["source"], "" if row["ok"] else "NOT SET")
        console.print(t)

    def approve(self, job: Dict, qa: Dict[str, Dict], channel: str) -> str:
        self.print_summary(job, qa)
        if settings.DRY_RUN:
            custom_print("WARNING", "[DRY RUN] Stopping before submit")
            return "dry"
        if not settings.MANUAL_APPROVAL:
            return "y"
        console.print(f"[bold green]READY TO SUBMIT[/bold green] via {channel}: {job.get('title')} @ {job.get('company')}")
        r = input("Submit? (y = submit / n = skip / e = I'll edit in the browser first): ").strip().lower()
        if r == "e":
            input("Edit the form in the browser, then press ENTER to submit...")
            return "edited"
        return "y" if r == "y" else "n"

    def _record(self, qa: Dict[str, Dict], f: Field, a: Answer, ok: bool, got: str):
        val = a.value
        if f.kind == "file":
            val = str(a.value).replace("\\", "/").split("/")[-1]
        elif f.kind == "textarea" and isinstance(val, str) and len(val) > 160:
            val = val[:157] + "..."
        qa[f.text[:200]] = {"question": f.text[:200], "answer": val, "source": a.tag(), "ok": ok, "kind": f.kind}

    def _fill_pass(self, engine: FormEngine, snap: Snapshot, job: Dict, ctx: Dict, qa: Dict, attempted: set,
                   skip_field: Callable[[Field], bool] = None) -> Optional[ApplyResult]:
        done_now: set = set()
        for pass_no in range(3):
            need = [f for f in snap.fields if self.answerer._needs_answer(f) and (f.text not in attempted or f.errors)
                    and f.text not in done_now and f.text not in ctx.get("just_fixed", set())]
            need = [f for f in need if not re.search(r"(deselect|select) resume", f.label or "", re.I)]
            if skip_field:
                need = [f for f in need if not skip_field(f)]
            if not need:
                return None
            codes = [f for f in need if CODE_RE.search(f.text)]
            if codes:
                if not self.human_gate(f"Enter the verification code for '{codes[0].text[:80]}' (check your email)"):
                    return ApplyResult("manual_review_needed", "Verification code required")
                need = [f for f in need if f not in codes]
                for f in codes:
                    attempted.add(f.text)
            for f in need:
                if f.kind == "combobox" and not f.options and not f.filled:
                    engine.probe_options(f)
            ctx["snapshot_fields"] = snap.fields
            answers = run_async(self.answerer.answer_fields(need, job, ctx))
            blockers = [f for f in need if f.required and (answers.get(f.fid) is None or answers[f.fid].needs_human or str(answers[f.fid].value).strip() == "")]
            blockers = [f for f in blockers if not (f.kind == "file" and f.filled)]
            for f in need:
                attempted.add(f.text)
                done_now.add(f.text)
                a = answers.get(f.fid)
                if a is None or a.value is None or str(a.value).strip() == "":
                    continue
                if not engine.present(f):
                    custom_print("FORM", f"– {f.text[:60]} disappeared after an earlier answer (conditional field) - skipped")
                    continue
                ok, got = engine.fill(f, a.value)
                self._record(qa, f, a, ok, got)
                if ok:
                    custom_print("FORM", f"✓ [{a.tag()}] {f.text[:60]} → {str(a.value)[:70]}")
                else:
                    self.answerer.discard(f, ctx)
                    custom_print("WARNING", f"✗ [{a.tag()}] {f.text[:60]} → {str(a.value)[:50]} ({got})")
                    if f.required and f not in blockers:
                        blockers.append(f)
            if blockers:
                names = "; ".join(b.text[:70] for b in blockers[:4])
                for b in blockers:
                    if b.kind != "file" and not PROFILE_ENTRY_RE.search(f"{b.raw.get('section') or ''} {b.text}"):
                        self.answerer.bank.record_unanswered(b.text, b.kind, [o for o in (b.options or []) if o != b.raw.get("placeholderOption")])
                if not self.human_gate(f"Required field(s) need you: {names}"):
                    return ApplyResult("manual_review_needed", f"Needs human input: {names}")
                for b in blockers:
                    qa[b.text[:200]] = {"question": b.text[:200], "answer": "(filled by you)", "source": "you", "ok": True, "kind": b.kind}
                    (ctx.get("bank_pending") or {}).pop(b.text, None)
            time.sleep(random.uniform(0.6, 1.2))
            snap = engine.scan()
        return None

    def _detect_submitted(self, engine: FormEngine, page: Page, before_url: str) -> bool:
        for _ in range(4):
            time.sleep(1.5)
            try:
                s = engine.scan()
            except Exception:
                continue
            if s.success:
                return True
            if re.search(r"thank|confirmation|success|submitted|complete", page.url or "", re.I) and page.url != before_url:
                return True
        return False

    def run(self, page: Page, job: Dict, channel: str, root_selector: Optional[str] = None, auto_submit: bool = True,
            max_steps: int = None, before_step: Callable[[FormEngine, Snapshot], Optional[ApplyResult]] = None,
            skip_field: Callable[[Field], bool] = None, strict_root: bool = False) -> ApplyResult:
        ctx: Dict[str, Any] = {}
        result = self._run(page, job, channel, root_selector, auto_submit, max_steps, before_step, skip_field, strict_root, ctx)
        if result.status in ("success", "submitted_unconfirmed"):
            self.answerer.commit_bank(ctx)
        return result

    def _learn_from_edits(self, engine: FormEngine, ctx: Dict, qa: Dict):
        from src.services.form_engine.matching import norm
        pending = ctx.get("bank_pending") or {}
        try:
            snap = engine.scan()
        except Exception:
            return
        for f in snap.fields:
            row = pending.get(f.text)
            if not row or f.kind == "file":
                continue
            current = str(f.value or "").strip()
            if f.kind in ("radio", "checkbox", "toggle"):
                continue
            if current and norm(current) != norm(row[3]):
                pending[f.text] = (row[0], row[1], row[2], current, row[4], row[5], "you")
                qa[f.text[:200]] = {"question": f.text[:200], "answer": current, "source": "you", "ok": True, "kind": f.kind}
            elif not current:
                pending.pop(f.text, None)

    def _run(self, page: Page, job: Dict, channel: str, root_selector: Optional[str], auto_submit: bool,
             max_steps: Optional[int], before_step, skip_field, strict_root: bool, ctx: Dict[str, Any]) -> ApplyResult:
        engine = FormEngine(page, root_selector, human_typing=settings.HUMAN_TYPING, strict_root=strict_root)
        qa: Dict[str, Dict] = {}
        attempted: set = set()
        last_sig, same, fixes = None, 0, 0
        max_steps = max_steps or settings.MAX_FORM_STEPS
        for step in range(1, max_steps + 1):
            time.sleep(random.uniform(0.8, 1.6))
            snap = engine.scan()
            if before_step:
                r = before_step(engine, snap)
                if r:
                    r.steps, r.channel, r.qa = step, channel, list(qa.values())
                    return r
                snap = engine.scan()
            if snap.success:
                return ApplyResult("success", None, step, channel, qa=list(qa.values()))
            if snap.captcha:
                if not self.human_gate("Solve the captcha / verification in the browser"):
                    return ApplyResult("manual_review_needed", "Captcha", step, channel, qa=list(qa.values()))
                continue
            sig = snap.signature()
            if sig == last_sig:
                same += 1
            else:
                last_sig, same, fixes = sig, 0, 0
            custom_print("APPLYING", f"Step {step}: {len(snap.fields)} fields, buttons: {[b.text[:20] for b in snap.buttons if b.kind in ('next', 'review', 'submit')]}" + (f", progress {snap.progress}%" if snap.progress else ""))

            blocked = self._fill_pass(engine, snap, job, ctx, qa, attempted, skip_field)
            if blocked:
                blocked.steps, blocked.channel, blocked.qa = step, channel, list(qa.values())
                return blocked
            snap = engine.scan()

            submit = snap.button("submit")
            if submit:
                if not auto_submit and not settings.MANUAL_APPROVAL:
                    self.print_summary(job, qa)
                    return ApplyResult("manual_review_needed", f"Filled - {channel} needs a human submit (auto-submit off for this system)", step, channel, qa=list(qa.values()))
                decision = self.approve(job, qa, channel)
                if decision == "dry":
                    return ApplyResult("dry_run", None, step, channel, qa=list(qa.values()))
                if decision == "edited":
                    self._learn_from_edits(engine, ctx, qa)
                    snap = engine.scan()
                    submit = snap.button("submit") or submit
                elif decision != "y":
                    return ApplyResult("skipped_by_user", "User declined", step, channel, qa=list(qa.values()))
                before = page.url
                custom_print("APPLYING", f"Submitting via '{submit.text}'...")
                engine.click(submit, wait=3.0)
                ctx["just_fixed"] = set()
                if self._detect_submitted(engine, page, before):
                    return ApplyResult("success", None, step, channel, qa=list(qa.values()))
                after = engine.scan()
                errs = after.all_errors()
                if errs and fixes < settings.MAX_VALIDATION_RETRIES and settings.ENABLE_VALIDATION_RETRY:
                    fixes += 1
                    self._fix(engine, after, job, ctx, qa)
                    continue
                if not after.button("submit") and not after.fields:
                    return ApplyResult("submitted_unconfirmed", "Submitted - no confirmation text detected", step, channel, qa=list(qa.values()))
                if same >= 2:
                    return ApplyResult("manual_review_needed", f"Submit did not go through: {'; '.join(errs[:3]) or 'no confirmation'}", step, channel, qa=list(qa.values()))
                continue

            nxt = snap.button("review", "next")
            if nxt and same < 3:
                engine.click(nxt, wait=2.0)
                ctx["just_fixed"] = set()
                after = engine.scan()
                if after.success:
                    return ApplyResult("success", None, step, channel, qa=list(qa.values()))
                errs = after.all_errors()
                if errs and after.signature() == sig:
                    custom_print("WARNING", f"Validation: {errs[:3]}")
                    if settings.ENABLE_VALIDATION_RETRY and fixes < settings.MAX_VALIDATION_RETRIES:
                        fixes += 1
                        self._fix(engine, after, job, ctx, qa)
                        continue
                    if not self.human_gate(f"Fix validation errors: {'; '.join(errs[:3])}"):
                        return ApplyResult("manual_review_needed", f"Validation failed: {'; '.join(errs[:3])}", step, channel, qa=list(qa.values()))
                continue

            if self.vision:
                act = self.vision.next_action(page, snap, job, "apply")
                if act:
                    custom_print("AI", f"Vision assist: {act.get('action')} {act.get('target')} ({act.get('reason', '')[:80]})")
                    a = act.get("action")
                    if a == "click":
                        b = next((x for x in snap.buttons if x.raw["bid"] == act.get("target")), None)
                        if b and b.kind in ("next", "apply", "other") and not RISKY_BTN_RE.search(f"{b.text} {b.raw.get('aria', '')}"):
                            engine.click(b)
                            continue
                        if b:
                            custom_print("WARNING", f"Vision suggested '{b.text}' - not clicking automatically (could submit or discard)")
                    elif a == "done":
                        return ApplyResult("submitted_unconfirmed", "Vision assist believes it was submitted", step, channel, qa=list(qa.values()))
                    elif a == "human":
                        if self.human_gate(act.get("reason") or "The page needs you"):
                            continue
            if self.human_gate("I can't find the next step on this page - move it forward manually"):
                continue
            return ApplyResult("manual_review_needed", "Complex form - couldn't progress", step, channel, qa=list(qa.values()))
        return ApplyResult("error", "Max steps exceeded", max_steps, channel, qa=list(qa.values()))

    def _fix(self, engine: FormEngine, snap: Snapshot, job: Dict, ctx: Dict, qa: Dict):
        bad = [f for f in snap.fields if f.errors or f.invalid]
        if not bad:
            msgs = snap.errors
            bad = [f for f in snap.fields if f.required and not f.filled]
            for f in bad:
                f.raw["errors"] = msgs[:2] or ["required"]
        if not bad:
            return
        custom_print("WARNING", f"Fixing {len(bad)} field(s) with AI: {[f.text[:40] for f in bad]}")
        prev = {f.fid: qa.get(f.text[:200], {}).get("answer") for f in bad}
        fixed = run_async(self.answerer.fix_errors(bad, prev, job, ctx))
        jf = ctx.setdefault("just_fixed", set())
        for f in bad:
            a = fixed.get(f.fid)
            jf.add(f.text)
            if a and str(a.value).strip():
                ok, got = engine.fill(f, a.value)
                self._record(qa, f, a, ok, got)
                custom_print("FORM", f"{'✓' if ok else '✗'} [fix] {f.text[:60]} → {str(a.value)[:60]}")
