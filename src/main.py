import sys
import os
import time
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import nest_asyncio
from playwright.sync_api import sync_playwright

nest_asyncio.apply()

from src.config import settings
from src.services.session_manager import SessionManager
from src.services.database import Database
from src.services.job_scraper import JobScraper
from src.services.job_evaluator import JobEvaluator
from src.services.browser import launch_context, main_page, save_cookies, SessionExpired, linkedin_logged_in
from src.services.appliers import FormRunner, LinkedInApplier, ExternalApplier, ApplyResult, detect_ats
from src.services.answer_bank import AnswerBank
from src.utils.logger import (
    console, print_header, print_success, print_error, print_warning, print_info, print_stats_table, print_run_summary, custom_print
)
import migrate_db

APPLIED_STATUSES = ("success", "submitted_unconfirmed")


def init_db() -> Database:
    db = Database(settings.DB_PATH)
    migrate_db.apply_v2(settings.DB_PATH)
    return db


def preflight(need_session: bool = True) -> bool:
    init_db()
    if not settings.load_api_key_from_file("gemini_key"):
        print_error("Gemini API key not found - add GEMINI_API_KEY to .env")
        return False
    if need_session and not SessionManager().session_exists():
        print_warning("No browser profile / LinkedIn session yet.")
        if input("Log in now? (y/n): ").strip().lower() != "y":
            return False
        setup()
    return True


def build_appliers():
    runner = FormRunner()
    external = ExternalApplier(runner)
    return LinkedInApplier(runner, external), external


def report(result: dict):
    s, e = result["status"], result.get("error")
    if s == "success":
        print_success(f"Application submitted! ({result.get('steps')} steps, {result.get('channel')})")
    elif s == "submitted_unconfirmed":
        print_warning(f"Submitted but no confirmation detected ({result.get('channel')})")
    elif s in ("manual_review_needed", "external"):
        print_warning(f"Needs manual review: {e}")
    elif s in ("already_applied", "expired", "skipped", "skipped_by_user", "dry_run"):
        custom_print("INFO", f"{s}: {e or ''}")
    else:
        print_error(f"Failed ({s}): {e}")


def apply_job(page, job: dict, li: LinkedInApplier, ext: ExternalApplier) -> dict:
    try:
        if job.get("external_url") and job.get("apply_type") == "external" and settings.EXTERNAL_APPLY:
            ext_page = page.context.new_page()
            try:
                result = ext.apply(ext_page, job, url=job["external_url"])
            finally:
                try:
                    ext_page.close()
                except Exception:
                    pass
        else:
            result = li.apply(page, job)
    except SessionExpired:
        raise
    except Exception as e:
        custom_print("ERROR", f"Crash during application: {e}")
        result = ApplyResult("error", f"Crash: {str(e)[:300]}", 0)
    return result.as_dict()


def setup():
    print_header("LinkedIn Boss Setup")
    SessionManager().save_session()
    print_success("Setup complete!")


def run(max_apps: int = None):
    max_apps = max_apps or settings.MAX_APPLICATIONS_PER_DAY
    print_header("LinkedIn Boss v2")
    console.print(f"[cyan]Manual approval:[/cyan] {settings.MANUAL_APPROVAL}   [cyan]Dry run:[/cyan] {settings.DRY_RUN}   "
                  f"[cyan]Max/day:[/cyan] {max_apps}   [cyan]External apply:[/cyan] {settings.EXTERNAL_APPLY}   "
                  f"[cyan]Easy Apply only:[/cyan] {settings.EASY_APPLY_ONLY}")
    if not preflight():
        return
    db = Database(settings.DB_PATH)
    scraped = evaluated = applied = 0
    with sync_playwright() as p:
        ctx = launch_context(p)
        page = main_page(ctx)
        evaluator = JobEvaluator(settings)
        scraper = JobScraper(settings, db)
        li, ext = build_appliers()
        try:
            page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
            time.sleep(3)
            if not linkedin_logged_in(page):
                raise SessionExpired("Not logged in to LinkedIn")
            empty_scrapes = 0
            session_done = set()
            while True:
                today = db.get_daily_count()
                remaining = max_apps - today
                print_header("Pipeline Status")
                st = db.get_stats()
                console.print(f"Applications today: {today}/{max_apps} | Jobs: {st['total_jobs']} | Evaluated: {st['total_evaluated']}")
                if remaining <= 0:
                    print_warning(f"Daily limit reached ({today}/{max_apps})")
                    break
                queue = db.get_unapplied_good_jobs(settings.SORT_QUEUE_BY_PAY, settings.EXTERNAL_APPLY and not settings.EASY_APPLY_ONLY, settings.QUEUE_MAX_AGE_DAYS)
                queue = [j for j in queue if j["id"] not in session_done]
                if queue:
                    batch = queue[:remaining]
                    print_header(f"Applying to {len(batch)} jobs (highest pay first)" if settings.SORT_QUEUE_BY_PAY else f"Applying to {len(batch)} jobs")
                    for idx, job in enumerate(batch):
                        if db.get_daily_count() >= max_apps:
                            break
                        if idx and idx % 10 == 0:
                            page = SessionManager().recycle_page(ctx, page)
                        ev = job.get("evaluation", {})
                        pay = f" | ~NZ${ev['pay_nzd']:,.0f} ({ev.get('pay_basis')})" if ev.get("pay_nzd") else ""
                        console.print(f"\n[cyan]{'=' * 70}[/cyan]\n[bold][{idx + 1}/{len(batch)}] {job['title']}[/bold] @ {job['company']}")
                        console.print(f"{job.get('location') or ''} | {job.get('apply_type') or '?'} | {ev.get('confidence')}%{pay}\n{(ev.get('reason') or '')[:160]}")
                        if db.recent_duplicate(job["company"], job["title"], settings.REPOST_COOLDOWN_DAYS, job["id"]):
                            db.insert_application(job["id"], {"status": "skipped", "error": "Repost of a role already applied to"})
                            custom_print("SKIP", "Repost of a role already applied to")
                            continue
                        result = apply_job(page, job, li, ext)
                        session_done.add(job["id"])
                        if not settings.DRY_RUN and result["status"] != "dry_run":
                            db.insert_application(job["id"], result)
                        report(result)
                        if result["status"] in APPLIED_STATUSES:
                            applied += 1
                        if idx < len(batch) - 1 and result["status"] not in ("already_applied", "expired", "skipped"):
                            delay = random.uniform(settings.MIN_DELAY_BETWEEN_APPS, settings.MAX_DELAY_BETWEEN_APPS)
                            if result["status"] not in APPLIED_STATUSES:
                                delay /= 3
                            console.print(f"[dim]Waiting {delay / 60:.1f} min...[/dim]")
                            time.sleep(delay)
                    continue
                pending = db.get_unevaluated_jobs()
                if pending:
                    print_header(f"Evaluating {len(pending)} jobs")
                    evaluator.filter_jobs_sync(pending, settings.CONFIDENCE_THRESHOLD, page=page, db=db)
                    evaluated += len(pending)
                    if evaluator.last_errors and len(db.get_unevaluated_jobs()) >= len(pending):
                        print_error("Evaluation is failing (Gemini errors) - stopping. Run: python src/main.py doctor")
                        break
                    continue
                print_header("Scraping new jobs")
                jobs = scraper.scrape_recommended_jobs(page, settings.MAX_JOBS_TO_SCRAPE)
                new = 0
                for j in jobs:
                    jid = db.insert_job(j)
                    if jid > 0 and not db.is_job_already_processed(jid):
                        new += 1
                scraped += new
                custom_print("SUCCESS", f"Added {new} new jobs")
                if new == 0:
                    empty_scrapes += 1
                    if empty_scrapes >= 2:
                        print_warning("No new jobs found in two scrape rounds - stopping.")
                        break
        except SessionExpired as e:
            print_error(str(e))
            console.print("Run option [4] Setup to log in again.")
        except KeyboardInterrupt:
            print_warning("Stopped by user")
        finally:
            save_cookies(ctx)
            ctx.close()
    print_run_summary(scraped=scraped, evaluated=evaluated, applied=applied, today_total=db.get_daily_count(), daily_limit=max_apps)
    from src.services.ai_service import AIService
    if AIService().usage_line():
        print_info(AIService().usage_line())


def apply_single(job_input: str):
    job_input = job_input.strip()
    if not preflight():
        return
    db = Database(settings.DB_PATH)
    is_linkedin = job_input.isdigit() or "linkedin.com" in job_input
    with sync_playwright() as p:
        ctx = launch_context(p)
        page = main_page(ctx)
        li, ext = build_appliers()
        try:
            if is_linkedin:
                m = __import__("re").search(r"(\d{6,})", job_input)
                jid = m.group(1) if m else job_input
                url = f"https://www.linkedin.com/jobs/view/{jid}/"
                existing = db.get_job_by_linkedin_id(jid)
                evaluator = JobEvaluator(settings)
                page.goto(url, wait_until="domcontentloaded")
                time.sleep(3)
                title = page.evaluate("() => (document.querySelector('h1') || {}).innerText || document.title.split('|')[0]").strip()
                company = page.evaluate("""() => { const a = document.querySelector('.job-details-jobs-unified-top-card__company-name a, a[href*="/company/"]'); return a ? a.innerText.trim() : ''; }""")
                job = existing or {"linkedin_job_id": jid, "title": title or "Unknown", "company": company or "Unknown", "url": url}
                details = evaluator.extract_details(job, page) or {}
                job.update({k: v for k, v in details.items() if v and k != "top"})
                job["id"] = existing["id"] if existing else db.insert_job(job)
                db.update_job_details(job["id"], details)
                if not settings.DRY_RUN and not db.is_job_already_processed(job["id"]):
                    db.insert_evaluation(job["id"], {"apply": True, "confidence": 100, "reason": "Manually selected"})
                result = li.apply(page, job).as_dict()
            else:
                title = ""
                page.goto(job_input, wait_until="domcontentloaded")
                time.sleep(3)
                title = page.title()
                job = {"linkedin_job_id": None, "title": title.split("|")[0].split(" - ")[0].strip() or "Unknown", "company": input("Company name: ").strip() or "Unknown",
                       "url": job_input, "description": page.evaluate("() => document.body.innerText.slice(0, 9000)"), "apply_type": "external", "external_url": job_input}
                job["id"] = db.insert_job({**job, "linkedin_job_id": "ext-" + __import__("hashlib").sha1(job_input.encode()).hexdigest()[:16]})
                if not settings.DRY_RUN:
                    db.insert_evaluation(job["id"], {"apply": True, "confidence": 100, "reason": "Manually selected"})
                result = ext.apply(page, job).as_dict()
            # a dry run never records results (a failed dry run would otherwise take the job out of the queue)
            if not settings.DRY_RUN and result["status"] != "dry_run":
                db.insert_application(job["id"], result)
            report(result)
        except SessionExpired as e:
            print_error(str(e))
        finally:
            save_cookies(ctx)
            ctx.close()


def run_retry(statuses=("manual_review_needed", "error"), title="Retry Failed / Manual Review Jobs", max_age=None):
    print_header(title)
    if not preflight():
        return
    db = Database(settings.DB_PATH)
    jobs = db.get_jobs_for_retry(max_age_days=max_age if max_age is not None else settings.RETRY_MAX_AGE_DAYS, statuses=statuses)
    if not jobs:
        print_info("Nothing to retry.")
        return
    print_info(f"{len(jobs)} jobs to retry")
    done = 0
    with sync_playwright() as p:
        ctx = launch_context(p)
        page = main_page(ctx)
        li, ext = build_appliers()
        try:
            for idx, job in enumerate(jobs):
                console.print(f"\n[bold][{idx + 1}/{len(jobs)}] {job['title']}[/bold] @ {job['company']} ({job.get('external_url') or job['url']})")
                result = apply_job(page, job, li, ext)
                if result["status"] in ("no_easy_apply",):
                    result["status"] = "expired"
                if not settings.DRY_RUN and result["status"] != "dry_run":
                    db.insert_application(job["id"], result)
                report(result)
                if result["status"] in APPLIED_STATUSES:
                    done += 1
                    if idx < len(jobs) - 1:
                        time.sleep(random.uniform(settings.MIN_DELAY_BETWEEN_APPS, settings.MAX_DELAY_BETWEEN_APPS) / 2)
        except SessionExpired as e:
            print_error(str(e))
        except KeyboardInterrupt:
            print_warning("Stopped by user")
        finally:
            save_cookies(ctx)
            ctx.close()
    print_success(f"Retry complete: {done}/{len(jobs)} submitted")


def external_queue():
    settings.MANUAL_APPROVAL = True
    run_retry(("manual_review_needed", "external"), "External Applications Queue (assisted)", max_age=60)


def stats():
    db = init_db()
    print_header("Application Statistics")
    print_stats_table(db.get_stats())
    rows = db.channel_stats()
    if rows:
        console.print("[bold]By channel[/bold]")
        for ch, status, n in rows:
            console.print(f"  {ch:22} {status:24} {n}")
    console.print(f"\n[bold]Answer bank:[/bold] {AnswerBank(settings.DB_PATH).counts()}")


def answers_review():
    init_db()
    bank = AnswerBank(settings.DB_PATH)
    open_qs = bank.all("unanswered")
    if open_qs:
        print_header(f"Questions that stopped applications ({len(open_qs)})")
        console.print("Type the answer once (it is reused on every form, and `retry` re-applies). Enter = skip, q = quit\n")
        for i, r in enumerate(open_qs, 1):
            console.print(f"[cyan][{i}/{len(open_qs)}][/cyan] [bold]{r['question'][:300]}[/bold]  [dim]{r['family']}[/dim]")
            if r.get("options_json") and r["options_json"] not in ("[]", "null"):
                console.print(f"   options: {r['options_json'][:300]}")
            new = input("   answer: ").strip()
            if new.lower() == "q":
                break
            if new:
                bank.set_status(r["id"], "approved", new)
    rows = bank.pending()
    print_header(f"Answer bank review ({len(rows)} unreviewed)")
    if not rows:
        print_info("Nothing to review.")
        return
    console.print("For each saved answer: [green]a[/green]=approve  [yellow]e[/yellow]=edit  [red]r[/red]=reject (never reuse)  s=skip  q=quit\n")
    for i, r in enumerate(rows, 1):
        scope = r["scope"] + (f" ({r['region']})" if r["region"] else "")
        console.print(f"[cyan][{i}/{len(rows)}][/cyan] [bold]{r['question'][:300]}[/bold]  [dim]{r['family']}, {scope}, used {r['uses']}x[/dim]")
        if r.get("options_json") and r["options_json"] not in ("[]", "null"):
            console.print(f"   options: {r['options_json'][:300]}")
        console.print(f"   answer: [white]{r['answer'][:500]}[/white]")
        c = input("   > ").strip().lower()
        if c == "a":
            bank.set_status(r["id"], "approved")
        elif c == "e":
            new = input("   new answer: ").strip()
            if new:
                bank.set_status(r["id"], "approved", new)
        elif c == "r":
            bank.set_status(r["id"], "rejected")
        elif c == "q":
            break
    console.print(f"\n{bank.counts()}")


def doctor():
    print_header("Doctor")
    init_db()
    migrate_db.apply_v2(settings.DB_PATH, verbose=True)
    key = settings.load_api_key_from_file("gemini_key")
    console.print(f"Gemini key: {'[green]found[/green]' if key else '[red]missing[/red]'}")
    if key:
        try:
            from src.services.ai_service import AIService
            models = AIService().list_models()
            console.print(f"Available Gemini models ({len(models)}): {', '.join(m for m in models if 'gemini-3' in m or 'gemini-2.5' in m)[:900]}")
            for role, chain in settings.MODELS.items():
                pick = next((m for m in chain if m in models), None)
                console.print(f"  {role:7} -> {'[green]' + pick + '[/green]' if pick else '[red]none of ' + str(chain) + '[/red]'}")
        except Exception as e:
            console.print(f"[red]Model listing failed: {e}[/red]")
    cs = Database(settings.DB_PATH).ai_cache_stats()
    console.print(f"AI answer cache: {cs['entries']} saved answers, reused {cs['hits']} times "
                  f"(saved {cs['input_tokens_saved']:,} input + {cs['output_tokens_saved']:,} output tokens) | "
                  f"thinking level {settings.THINKING_LEVEL} | Gemini context cache {'on' if settings.AI_EXPLICIT_CACHE else 'off'}")
    try:
        import docx
        console.print("python-docx: [green]ok[/green]")
    except ImportError:
        console.print("python-docx: [red]missing[/red] (pip install python-docx) - cover letters will be .txt")
    for lane in settings.CV_FILES:
        p = settings.cv_for_lane(lane)
        console.print(f"CV ({lane}): {'[green]' + str(p) + '[/green]' if p else '[red]not found: ' + settings.CV_FILES[lane] + '[/red]'}")
    console.print(f"ATS account email/password in .env: {'yes' if settings.env('ATS_ACCOUNT_EMAIL') and settings.env('ATS_ACCOUNT_PASSWORD') else 'no (Workday sign-in will ask you)'}")
    console.print(f"Browser profile: {settings.PROFILE_DIR} ({'exists' if SessionManager().session_exists() else 'not set up - run setup'})")
    if input("Open the browser and check the LinkedIn login? (y/n): ").strip().lower() == "y":
        with sync_playwright() as p:
            ctx = launch_context(p)
            page = main_page(ctx)
            page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
            time.sleep(4)
            console.print(f"LinkedIn logged in: {'[green]yes[/green]' if linkedin_logged_in(page) else '[red]no - run setup[/red]'}")
            ctx.close()


def capture():
    print_header("Capture page structure")
    from datetime import datetime
    from src.services.appliers.linkedin import LinkedInApplier
    url = input("LinkedIn job URL/number or any application page URL: ").strip()
    if url.isdigit():
        url = f"https://www.linkedin.com/jobs/view/{url}/"
    out = settings.FIXTURE_DIR / datetime.now().strftime("%Y%m%d_%H%M%S")
    out.mkdir(parents=True, exist_ok=True)

    def dump(page, tag):
        page.screenshot(path=str(out / f"{tag}.png"))
        for i, fr in enumerate(page.frames):
            try:
                html = fr.content()
            except Exception:
                continue
            (out / f"{tag}_frame{i}.html").write_text(f"<!-- {fr.url} -->\n" + html, encoding="utf-8")
        console.print(f"  saved {tag} ({len(page.frames)} frames)")

    with sync_playwright() as p:
        ctx = launch_context(p)
        page = main_page(ctx)
        page.goto(url, wait_until="domcontentloaded")
        time.sleep(5)
        dump(page, "1_page")
        if "linkedin.com" in url:
            li = LinkedInApplier()
            state = li.job_state(page)
            console.print(f"  job state: {state}")
            btn = li._apply_locator(page, easy=bool(state.get("easy")))
            if btn and input("Click the apply button and capture the first form step (nothing is submitted)? (y/n): ").strip().lower() == "y":
                btn.click()
                time.sleep(6)
                console.print(f"  apply UI: {li.ui_state(page)}")
                dump(page, "2_apply")
                input("Move through more steps manually if you like, press ENTER to capture again...")
                dump(page, "3_apply")
                li.close_modal(page)
        else:
            console.print(f"  application system: {detect_ats(page.url, page)}")
            input("Navigate to the form if needed, then press ENTER to capture...")
            dump(page, "2_form")
        ctx.close()
    print_success(f"Captured to {out}")


def review():
    db = Database(settings.DB_PATH)
    jobs = db.get_jobs_for_manual_review()
    print_header("Jobs Needing Manual Review")
    if not jobs:
        print_info("No jobs need manual review!")
        return
    console.print(f"\nFound {len(jobs)} jobs:\n")
    for idx, job in enumerate(jobs):
        console.print(f"[cyan][{idx + 1}][/cyan] {job['title']}")
        console.print(f"    Company: {job['company']}")
        console.print(f"    Reason: {job['error_message']}")
        console.print(f"    URL: {job['url']}")
        console.print()


def search():
    print_header("Search Jobs")
    keyword = input("Enter search term (company name, job title, or keyword): ").strip()
    if not keyword:
        print_warning("No search term entered.")
        return
    db = Database(settings.DB_PATH)
    results = db.search_jobs(keyword)
    if not results:
        print_info(f"No jobs found matching '{keyword}'")
        return
    console.print(f"\n[green]Found {len(results)} job(s) matching '{keyword}':[/green]\n")
    for idx, job in enumerate(results):
        console.print(f"[cyan]{'=' * 70}[/cyan]")
        console.print(f"[bold][{idx + 1}] {job['title']}[/bold]")
        console.print(f"[cyan]Company:[/cyan] {job['company']}")
        console.print(f"[cyan]URL:[/cyan] {job['url']}")
        console.print(f"[cyan]Scraped:[/cyan] {job['scraped_at']}")
        if job['evaluation']:
            e = job['evaluation']
            console.print(f"\n[yellow]AI Evaluation:[/yellow] {'[green]YES[/green]' if e['apply'] else '[red]NO[/red]'} {e['confidence']}% - {e['reason']}")
        else:
            console.print("\n[dim]Not yet evaluated[/dim]")
        if job['application']:
            a = job['application']
            console.print(f"[yellow]Application:[/yellow] {a['status']} {a['error_message'] or ''} ({a['applied_at']})")
        else:
            console.print("[dim]Not yet applied[/dim]")
        if job['description']:
            console.print(f"\n[yellow]Description:[/yellow] {job['description'][:300]}...")
        console.print()
    console.print(f"[cyan]{'=' * 70}[/cyan]")
    pick = input("\nEnter job number to view full description (or press Enter to exit): ").strip()
    if pick.isdigit() and 0 < int(pick) <= len(results):
        job = results[int(pick) - 1]
        console.print(f"\n[bold]{job['title']} at {job['company']}[/bold]\n")
        console.print(job['description'] or "[dim]No description available[/dim]")


def reset_db():
    print_header("Reset Database")
    console.print("[yellow]⚠ This deletes ALL jobs, evaluations, applications, saved answers and stats.[/yellow]\n")
    if input("Type 'DELETE ALL' to confirm: ").strip() == "DELETE ALL":
        if os.path.exists(settings.DB_PATH):
            os.remove(settings.DB_PATH)
            print_success("Database deleted - a fresh one is created on next run.")
        else:
            print_info("Database doesn't exist.")
    else:
        console.print("[yellow]Cancelled.[/yellow]")


def run_interview_cmd(job_input: str = None):
    from src.services.interview_runner import run_interview
    print_header("Interview Assistant")
    db = Database(settings.DB_PATH)
    job_data = None
    if not job_input:
        console.print("Enter a LinkedIn job number, URL, or search keyword to load job context (Enter to skip).")
        job_input = input("Job number/URL/keyword: ").strip()
    if job_input:
        num = job_input.strip().rstrip('/')
        if num.startswith('http'):
            num = num.split('?')[0].rstrip('/').split('/')[-1]
        if num.isdigit():
            job_data = db.get_job_by_linkedin_id(num)
        if not job_data and not num.isdigit():
            results = db.search_jobs(job_input)
            if results:
                for idx, j in enumerate(results[:10]):
                    console.print(f"  [{idx + 1}] {j['title']} at {j['company']}")
                pick = input("\nSelect job number (or Enter to skip): ").strip()
                if pick.isdigit() and 1 <= int(pick) <= len(results):
                    job_data = results[int(pick) - 1]
        console.print(f"\n[green]Loaded:[/green] {job_data['title']} at {job_data['company']}" if job_data else "[yellow]Running without job context.[/yellow]")
    run_interview(job_data)


MENU = [
    ("1", "Run automation (manual approval)", "run", {"MANUAL_APPROVAL": True, "DRY_RUN": False}),
    ("2", "Run automation (auto mode - no approval)", "run", {"MANUAL_APPROVAL": False, "DRY_RUN": False}),
    ("3", "Dry run (fill forms, never submit)", "run", {"DRY_RUN": True}),
    ("4", "Setup (log in to LinkedIn / sites in the bot browser)", "setup", {}),
    ("5", "View statistics", "stats", {}),
    ("6", "Review jobs needing manual attention", "review", {}),
    ("7", "Reset database", "reset", {}),
    ("8", "Retry failed/manual jobs", "retry", {}),
    ("9", "Search jobs", "search", {}),
    ("10", "Apply to a specific job (LinkedIn URL/number or any application URL)", "apply", {"MANUAL_APPROVAL": True, "DRY_RUN": False}),
    ("11", "Interview assistant", "interview", {}),
    ("12", "Review saved answers (answer bank)", "answers", {}),
    ("13", "External applications queue (assisted)", "external", {}),
    ("14", "Doctor (check keys, models, CVs, browser)", "doctor", {}),
    ("15", "Capture page structure (debug)", "capture", {}),
]


def main():
    if len(sys.argv) < 2:
        print_header("LinkedIn Boss v2")
        for k, label, _, _ in MENU:
            console.print(f"[{k}] {label}")
        choice = input("\nEnter choice: ").strip()
        item = next((m for m in MENU if m[0] == choice), None)
        if not item:
            console.print("[red]Invalid choice.[/red]")
            return
        _, _, command, overrides = item
        for k, v in overrides.items():
            setattr(settings, k, v)
        if choice == "2" and input("[!] Auto mode submits without asking. Type 'yes' to continue: ").strip().lower() != "yes":
            return
        arg = None
    else:
        command = sys.argv[1].lower()
        arg = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else None
        if "--dry-run" in sys.argv:
            settings.DRY_RUN = True
        if "--no-approval" in sys.argv:
            settings.MANUAL_APPROVAL = False
        if "--approval" in sys.argv:
            settings.MANUAL_APPROVAL = True
        if "--easy-only" in sys.argv:
            settings.EASY_APPLY_ONLY = True
    commands = {
        "setup": setup, "run": run, "stats": stats, "review": review, "reset": reset_db, "retry": run_retry,
        "search": search, "answers": answers_review, "external": external_queue, "doctor": doctor, "capture": capture,
    }
    if command == "apply":
        apply_single(arg or input("LinkedIn job URL/number or application URL: ").strip())
    elif command == "interview":
        run_interview_cmd(arg)
    elif command in commands:
        commands[command]()
    else:
        console.print(f"[red]Unknown command: {command}[/red]  Valid: {', '.join(list(commands) + ['apply', 'interview'])}")
        sys.exit(1)


if __name__ == "__main__":
    main()
