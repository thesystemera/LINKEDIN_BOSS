import sys
import os
import time
import random
import nest_asyncio
from playwright.sync_api import sync_playwright

nest_asyncio.apply()

from src.config import settings
from src.services.session_manager import SessionManager
from src.services.database import Database
from src.services.job_scraper import JobScraper
from src.services.job_evaluator import JobEvaluator
from src.services.auto_applier import AutoApplier
from src.utils.logger import (
    console,
    print_header,
    print_success,
    print_error,
    print_warning,
    print_info,
    print_stats_table,
    print_run_summary,
    custom_print
)

def setup():
    print_header("LinkedIn Auto-Apply Setup")
    console.print("This will save your LinkedIn session for future runs.\n")

    session_mgr = SessionManager(settings.SESSION_PATH)
    session_mgr.save_session()

    print_success("Setup complete!")
    console.print("\nNext steps:")
    console.print("1. Add your Gemini API key to: .env (see .env.example)")
    console.print("2. Run: python src/main.py run")


def run(max_apps: int = None):
    max_apps = max_apps or settings.MAX_APPLICATIONS_PER_DAY

    print_header("LinkedIn Auto-Apply Settings")
    console.print(f"[cyan]Manual Approval:[/cyan] {settings.MANUAL_APPROVAL}")
    console.print(f"[cyan]Dry Run Mode:[/cyan] {settings.DRY_RUN}")
    console.print(f"[cyan]Max Apps/Day:[/cyan] {settings.MAX_APPLICATIONS_PER_DAY}")
    console.print()

    db = Database(settings.DB_PATH)
    session_mgr = SessionManager(settings.SESSION_PATH)

    if not session_mgr.session_exists():
        print_warning("No LinkedIn session found!")
        console.print("\n[yellow]First time setup needed - I'll walk you through it.[/yellow]\n")
        response = input("Ready to login to LinkedIn? (y/n): ").lower().strip()
        if response != 'y':
            console.print("\n[red]Setup cancelled. Run again when ready![/red]")
            return
        setup()
        console.print("\n[green]✓ Setup complete! Starting automation...[/green]\n")
        time.sleep(2)

    api_key = settings.load_api_key_from_file("gemini_key")
    if not api_key:
        print_error("Gemini API key not found!")
        console.print("\n[yellow]You need to add your Gemini API key:[/yellow]")
        console.print("1. Get your key from: https://aistudio.google.com/app/apikey")
        console.print("2. Add to .env: GEMINI_API_KEY=your_key_here")
        return

    session_scraped = 0
    session_evaluated = 0
    session_applied = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=settings.HEADLESS,
            slow_mo=settings.SLOW_MO
        )
        context = browser.new_context(viewport=settings.VIEWPORT)
        session_mgr.load_session(context)
        page = context.new_page()

        evaluator = JobEvaluator(settings)
        scraper = JobScraper(settings)
        applier = AutoApplier(settings)

        while True:
            today_count = db.get_daily_count()
            remaining = max_apps - today_count

            print_header("Pipeline Status")
            console.print(f"Applications today: {today_count}/{max_apps}")
            console.print(f"Remaining: {remaining}")

            stats = db.get_stats()
            custom_print("INFO",
                         f"Database: {stats['total_jobs']} jobs scraped, {stats['total_evaluated']} evaluated, {sum(stats['applications_by_status'].values())} applications submitted")
            if stats['applications_by_status']:
                status_summary = ', '.join(
                    [f"{status}: {count}" for status, count in stats['applications_by_status'].items()])
                custom_print("INFO", f"Application statuses: {status_summary}")

            if remaining <= 0:
                print_warning(f"Daily limit reached ({today_count}/{max_apps})")
                console.print("Try again tomorrow or increase MAX_APPLICATIONS_PER_DAY.")
                break

            unapplied_jobs = db.get_unapplied_good_jobs()
            unevaluated_jobs = db.get_unevaluated_jobs()

            if unapplied_jobs:
                count = len(unapplied_jobs)
                custom_print("INFO", f"Found {count} jobs ready for application. Processing now...")

                batch_to_apply = unapplied_jobs[:remaining]

                print_header(f"Applying to {len(batch_to_apply)} Jobs")

                for idx, job in enumerate(batch_to_apply):
                    if idx > 0 and idx % 10 == 0:
                        page = session_mgr.recycle_page(context, page)

                    console.print(f"\n[cyan]{'=' * 60}[/cyan]")
                    console.print(f"[bold][{idx + 1}/{len(batch_to_apply)}] {job['title']}[/bold]")
                    console.print(f"Company: {job['company']}")
                    console.print(f"Confidence: {job['evaluation']['confidence']}%")
                    console.print(f"Reason: {job['evaluation']['reason'][:100]}...")
                    console.print(f"[cyan]{'=' * 60}[/cyan]")

                    try:
                        result = applier.apply_to_job(page, job)
                    except Exception as e:
                        custom_print("ERROR", f"Fatal crash during application: {str(e)}")
                        result = {"status": "error", "error": f"Fatal crash: {str(e)}", "steps": 0}

                    db.insert_application(job['id'], result)

                    if result['status'] == 'success':
                        session_applied += 1
                        print_success(f"Application submitted! ({result['steps']} steps)")
                    elif result['status'] == 'manual_review_needed':
                        print_warning(f"Needs manual review: {result['error']}")
                    elif result['status'] == 'skipped':
                        custom_print("INFO", "Skipped (Already applied)")
                    else:
                        print_error(f"Failed: {result['error']}")

                    if idx < len(batch_to_apply) - 1:
                        delay = random.uniform(settings.MIN_DELAY_BETWEEN_APPS, settings.MAX_DELAY_BETWEEN_APPS)
                        console.print(f"\n[dim]Waiting {delay / 60:.1f} minutes before next application...[/dim]")
                        time.sleep(delay)

                continue

            elif unevaluated_jobs:
                custom_print("INFO", f"Found {len(unevaluated_jobs)} jobs waiting for evaluation.")
                print_header("Step 2: AI Evaluation")

                evaluator.filter_jobs_sync(unevaluated_jobs, settings.CONFIDENCE_THRESHOLD, page=page, db=db)

                session_evaluated += len(unevaluated_jobs)
                continue

            else:
                custom_print("INFO", "No pending work found. Starting scraper...")
                print_header("Step 1: Scraping Jobs")

                jobs = scraper.scrape_recommended_jobs(page, settings.MAX_JOBS_TO_SCRAPE)

                if not jobs:
                    print_warning("No new jobs found via scraping.")
                    console.print("Exiting loop.")
                    break

                new_jobs_count = 0
                skipped_count = 0

                custom_print("INFO", "Saving jobs to database...")
                for job in jobs:
                    job_id = db.insert_job(job)

                    if not db.is_job_already_processed(job_id):
                        new_jobs_count += 1
                    else:
                        skipped_count += 1
                        custom_print("SKIP", f"Already processed: {job['title'][:30]}...")

                if new_jobs_count == 0:
                    print_warning(f"All {len(jobs)} scraped jobs were duplicates. Stopping to avoid infinite loop.")
                    break

                session_scraped += new_jobs_count
                custom_print("SUCCESS", f"Added {new_jobs_count} new jobs to processing queue.")

                continue

        browser.close()

    print_run_summary(
        scraped=session_scraped,
        evaluated=session_evaluated,
        applied=session_applied,
        today_total=db.get_daily_count(),
        daily_limit=max_apps
    )

def apply_single(job_input: str):
    """Apply to a single job by URL or job number."""
    # Normalize input to a full URL
    job_input = job_input.strip()
    if job_input.startswith('http'):
        url = job_input.split('?')[0]  # Strip tracking params
    else:
        # Assume it's a job number
        url = f"https://www.linkedin.com/jobs/view/{job_input}/"

    # Extract linkedin_job_id from URL
    linkedin_job_id = url.rstrip('/').split('/')[-1]

    print_header("Apply to Specific Job")
    console.print(f"[cyan]URL:[/cyan] {url}")
    console.print(f"[cyan]Job ID:[/cyan] {linkedin_job_id}")
    console.print(f"[cyan]Manual Approval:[/cyan] {settings.MANUAL_APPROVAL}")
    console.print(f"[cyan]Dry Run:[/cyan] {settings.DRY_RUN}")
    console.print()

    db = Database(settings.DB_PATH)
    session_mgr = SessionManager(settings.SESSION_PATH)

    if not session_mgr.session_exists():
        print_error("No LinkedIn session found! Run setup first.")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=settings.HEADLESS,
            slow_mo=settings.SLOW_MO
        )
        context = browser.new_context(viewport=settings.VIEWPORT)
        session_mgr.load_session(context)
        page = context.new_page()

        # Navigate to job page and extract info
        custom_print("INFO", f"Navigating to job page...")
        page.goto(url, wait_until='domcontentloaded')
        time.sleep(3)

        current_url = page.url
        if 'authwall' in current_url or 'login' in current_url:
            print_error("LinkedIn redirected to login - session expired. Run setup.")
            browser.close()
            return

        # Extract title from page
        title = "Unknown Title"
        for sel in ['h1.t-24', 'h1.topcard__title', 'h1', '.job-details-jobs-unified-top-card__job-title']:
            elem = page.query_selector(sel)
            if elem:
                text = elem.inner_text().strip()
                if text:
                    title = text
                    break

        # Extract company from page
        company = "Unknown Company"
        for sel in ['.job-details-jobs-unified-top-card__company-name', '.topcard__org-name-link', '.job-details-jobs-unified-top-card__primary-description-container a']:
            elem = page.query_selector(sel)
            if elem:
                text = elem.inner_text().strip()
                if text:
                    company = text
                    break

        # Extract description
        evaluator = JobEvaluator(settings)
        description = evaluator._extract_job_description({'url': url, 'title': title}, page) or 'No Description Available'

        console.print(f"\n[bold]{title}[/bold]")
        console.print(f"Company: {company}")
        console.print(f"Description: {description[:200]}...")
        console.print()

        # Insert job into DB (deduplicates by linkedin_job_id)
        job_data = {
            'linkedin_job_id': linkedin_job_id,
            'title': title,
            'company': company,
            'url': url,
            'description': description,
        }
        job_id = db.insert_job(job_data)
        custom_print("INFO", f"Job in database (id={job_id})")

        # Insert synthetic evaluation (user explicitly chose this job)
        if not db.is_job_already_processed(job_id):
            db.insert_evaluation(job_id, {
                'apply': True,
                'confidence': 100,
                'reason': 'Manually selected by user'
            })
            custom_print("INFO", "Created evaluation (manually selected)")
        else:
            custom_print("INFO", "Job already has evaluation in database")

        # Build job dict in the format apply_to_job expects
        job = {
            'id': job_id,
            'title': title,
            'company': company,
            'url': url,
            'description': description,
            'evaluation': {
                'confidence': 100,
                'reason': 'Manually selected by user',
                'apply': True
            }
        }

        # Apply
        applier = AutoApplier(settings)
        try:
            result = applier.apply_to_job(page, job)
        except Exception as e:
            custom_print("ERROR", f"Fatal crash during application: {str(e)}")
            result = {"status": "error", "error": f"Fatal crash: {str(e)}", "steps": 0}

        db.insert_application(job_id, result)

        if result['status'] == 'success':
            print_success(f"Application submitted! ({result['steps']} steps)")
        elif result['status'] == 'manual_review_needed':
            print_warning(f"Needs manual review: {result['error']}")
        elif result['status'] == 'dry_run':
            print_info("Dry run complete - application was NOT submitted")
        elif result['status'] == 'skipped':
            custom_print("INFO", "Skipped (Already applied)")
        else:
            print_error(f"Failed: {result['error']}")

        browser.close()


def run_retry():
    print_header("Retry Failed / Manual Review Jobs")
    console.print(f"[cyan]Manual Approval:[/cyan] {settings.MANUAL_APPROVAL}")
    console.print(f"[cyan]Dry Run Mode:[/cyan] {settings.DRY_RUN}")

    db = Database(settings.DB_PATH)
    all_failed = db.get_jobs_for_retry()
    retry_jobs = db.get_jobs_for_retry(max_age_days=settings.RETRY_MAX_AGE_DAYS)

    if not retry_jobs:
        if all_failed:
            print_info(f"No recent jobs to retry ({len(all_failed)} failed jobs are older than {settings.RETRY_MAX_AGE_DAYS} days).")
        else:
            print_info("No failed or manual-review jobs found to retry!")
        return

    print_info(f"Found {len(retry_jobs)} jobs to retry (last {settings.RETRY_MAX_AGE_DAYS} days). {len(all_failed) - len(retry_jobs)} older jobs skipped.")

    session_mgr = SessionManager(settings.SESSION_PATH)
    if not session_mgr.session_exists():
        print_error("No LinkedIn session found! Run setup first.")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=settings.HEADLESS,
            slow_mo=settings.SLOW_MO
        )
        context = browser.new_context(viewport=settings.VIEWPORT)
        session_mgr.load_session(context)
        page = context.new_page()

        applier = AutoApplier(settings)
        session_applied = 0

        print_header(f"Retrying {len(retry_jobs)} Jobs")

        for idx, job in enumerate(retry_jobs):
            if idx > 0 and idx % 10 == 0:
                page = session_mgr.recycle_page(context, page)

            console.print(f"\n[cyan]{'=' * 60}[/cyan]")
            console.print(f"[bold][{idx + 1}/{len(retry_jobs)}] RETRYING: {job['title']}[/bold]")
            console.print(f"Company: {job['company']}")
            console.print(f"URL: {job['url']}")
            console.print(f"[cyan]{'=' * 60}[/cyan]")

            try:
                result = applier.apply_to_job(page, job)
            except Exception as e:
                custom_print("ERROR", f"Fatal crash during application: {str(e)}")
                result = {"status": "error", "error": f"Fatal crash: {str(e)}", "steps": 0}

            # In retry mode: only manual_review_needed is worth retrying.
            # Everything else (no_easy_apply, error, timeout) = expired, don't waste time again.
            if result['status'] in ('no_easy_apply', 'error'):
                result['status'] = 'expired'
                result['error'] = result.get('error', 'Job no longer available')
                custom_print("INFO", f"Marking as expired: {job['title']} at {job['company']}")

            db.insert_application(job['id'], result)

            if result['status'] == 'success':
                session_applied += 1
                print_success(f"Application submitted! ({result['steps']} steps)")
            elif result['status'] == 'expired':
                custom_print("INFO", "Job expired - removed from retry queue")
            elif result['status'] == 'manual_review_needed':
                print_warning(f"Still needs manual review: {result['error']}")
            elif result['status'] == 'skipped':
                custom_print("INFO", "Skipped")
            else:
                print_error(f"Failed: {result['error']}")

            if idx < len(retry_jobs) - 1 and result['status'] == 'success':
                delay = random.uniform(settings.MIN_DELAY_BETWEEN_APPS, settings.MAX_DELAY_BETWEEN_APPS)
                console.print(f"\n[dim]Waiting {delay / 60:.1f} minutes before next retry...[/dim]")
                time.sleep(delay)

        browser.close()

    print_success(f"Retry run complete. Successfully applied to {session_applied}/{len(retry_jobs)} jobs.")

def stats():
    db = Database(settings.DB_PATH)
    stats_data = db.get_stats()

    print_header("Application Statistics")
    print_stats_table(stats_data)

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
            eval_data = job['evaluation']
            apply_status = "[green]YES[/green]" if eval_data['apply'] else "[red]NO[/red]"
            console.print(f"\n[yellow]AI Evaluation:[/yellow]")
            console.print(f"  Apply: {apply_status}")
            console.print(f"  Confidence: {eval_data['confidence']}%")
            console.print(f"  Reason: {eval_data['reason']}")
        else:
            console.print(f"\n[dim]Not yet evaluated[/dim]")

        if job['application']:
            app_data = job['application']
            status_colors = {
                'success': 'green',
                'error': 'red',
                'manual_review_needed': 'yellow',
                'skipped': 'dim'
            }
            color = status_colors.get(app_data['status'], 'white')
            console.print(f"\n[yellow]Application:[/yellow]")
            console.print(f"  Status: [{color}]{app_data['status']}[/{color}]")
            if app_data['error_message']:
                console.print(f"  Error: {app_data['error_message']}")
            console.print(f"  Applied: {app_data['applied_at']}")
        else:
            console.print(f"\n[dim]Not yet applied[/dim]")

        if job['description']:
            desc_preview = job['description'][:300] + "..." if len(job['description']) > 300 else job['description']
            console.print(f"\n[yellow]Description Preview:[/yellow]")
            console.print(f"  {desc_preview}")

        console.print()

    # Option to view full description
    console.print(f"[cyan]{'=' * 70}[/cyan]")
    view_full = input("\nEnter job number to view full description (or press Enter to exit): ").strip()

    if view_full.isdigit():
        job_idx = int(view_full) - 1
        if 0 <= job_idx < len(results):
            job = results[job_idx]
            console.print(f"\n[bold]Full Description for: {job['title']} at {job['company']}[/bold]\n")
            console.print(job['description'] or "[dim]No description available[/dim]")
            console.print()

def reset_db():
    print_header("Reset Database")
    console.print("[yellow]⚠ This will delete ALL data:[/yellow]")
    console.print("  - All job records")
    console.print("  - All applications")
    console.print("  - All evaluations")
    console.print("  - Daily statistics\n")

    confirm = input("Are you SURE? Type 'DELETE ALL' to confirm: ").strip()

    if confirm == "DELETE ALL":
        if os.path.exists(settings.DB_PATH):
            os.remove(settings.DB_PATH)
            print_success("Database deleted!")
            console.print("A fresh database will be created on next run.")
        else:
            print_info("Database doesn't exist - nothing to delete.")
    else:
        console.print("[yellow]Cancelled.[/yellow]")

def run_interview_cmd(job_input: str = None):
    """Launch the interview assistant, optionally with a job from the database."""
    from src.services.interview_runner import run_interview

    print_header("Interview Assistant")

    db = Database(settings.DB_PATH)
    job_data = None

    if not job_input:
        console.print("Enter a LinkedIn job number, URL, or search keyword to load job context.")
        console.print("Or press Enter to run without job context.\n")
        job_input = input("Job number/URL/keyword (or Enter to skip): ").strip()

    if job_input:
        # Try as LinkedIn job number first
        job_number = job_input.strip().rstrip('/')
        if job_number.startswith('http'):
            job_number = job_number.split('?')[0].rstrip('/').split('/')[-1]

        if job_number.isdigit():
            job_data = db.get_job_by_linkedin_id(job_number)

        # If not found by ID, try keyword search
        if not job_data and not job_number.isdigit():
            results = db.search_jobs(job_input)
            if results:
                console.print(f"\n[green]Found {len(results)} matching job(s):[/green]\n")
                for idx, j in enumerate(results[:10]):
                    console.print(f"  [{idx + 1}] {j['title']} at {j['company']}")
                pick = input("\nSelect job number (or Enter to skip): ").strip()
                if pick.isdigit() and 1 <= int(pick) <= len(results):
                    job_data = results[int(pick) - 1]

        if job_data:
            console.print(f"\n[green]Loaded:[/green] {job_data.get('title', '?')} at {job_data.get('company', '?')}")
        else:
            console.print(f"\n[yellow]Job '{job_input}' not found in database. Running without job context.[/yellow]")

    run_interview(job_data)


def main():
    if len(sys.argv) < 2:
        print_header("LinkedIn Auto-Apply")
        console.print("What would you like to do?\n")
        console.print("[1] Run automation (with manual approval)")
        console.print("[2] Run automation (auto mode - no approval)")
        console.print("[3] Dry run (show what would happen, don't submit)")
        console.print("[4] Setup (login to LinkedIn)")
        console.print("[5] View statistics")
        console.print("[6] Review jobs needing manual attention")
        console.print("[7] Reset database (clear all data)")
        console.print("[8] Retry ALL failed/manual jobs (Auto Mode)")
        console.print("[9] Search jobs (find by company/title/keyword)")
        console.print("[10] Apply to specific job (URL or job number)")
        console.print("[11] Interview assistant (real-time AI prompts)\n")

        choice = input("Enter choice (1-11): ").strip()

        if choice == "1":
            command = "run"
            settings.MANUAL_APPROVAL = True
            settings.DRY_RUN = False
        elif choice == "2":
            command = "run"
            settings.MANUAL_APPROVAL = False
            settings.DRY_RUN = False
            console.print("\n[red]⚠ WARNING: Auto mode will submit applications without asking![/red]")
            confirm = input("Are you sure? (yes/no): ").strip().lower()
            if confirm != "yes":
                console.print("[yellow]Cancelled. Use option 1 for manual approval.[/yellow]")
                return
        elif choice == "3":
            command = "run"
            settings.DRY_RUN = True
        elif choice == "4":
            command = "setup"
        elif choice == "5":
            command = "stats"
        elif choice == "6":
            command = "review"
        elif choice == "7":
            command = "reset"
        elif choice == "8":
            command = "retry"
            settings.MANUAL_APPROVAL = False
            settings.DRY_RUN = False
        elif choice == "9":
            command = "search"
        elif choice == "10":
            command = "apply"
            settings.MANUAL_APPROVAL = True
            settings.DRY_RUN = False
        elif choice == "11":
            command = "interview"
        else:
            console.print("[red]Invalid choice. Exiting.[/red]")
            return

        console.print()
    else:
        command = sys.argv[1].lower()

        if '--dry-run' in sys.argv:
            settings.DRY_RUN = True
            console.print("[yellow]Dry run mode enabled[/yellow]")
        if '--no-approval' in sys.argv:
            settings.MANUAL_APPROVAL = False
            console.print("[yellow]Manual approval disabled[/yellow]")
        if '--approval' in sys.argv:
            settings.MANUAL_APPROVAL = True
            console.print("[yellow]Manual approval enabled[/yellow]")

    if command == "setup":
        setup()
    elif command == "run":
        run()
    elif command == "stats":
        stats()
    elif command == "review":
        review()
    elif command == "reset":
        reset_db()
    elif command == "retry":
        run_retry()
    elif command == "search":
        search()
    elif command == "apply":
        # Get job input from CLI args or prompt
        if len(sys.argv) > 2:
            job_input = sys.argv[2]
        else:
            job_input = input("Enter LinkedIn job URL or job number: ").strip()
            if not job_input:
                print_warning("No input provided.")
                return
        apply_single(job_input)
    elif command == "interview":
        if len(sys.argv) > 2:
            job_input = sys.argv[2]
        else:
            job_input = None
        run_interview_cmd(job_input)
    else:
        console.print(f"[red]Unknown command: {command}[/red]")
        console.print("Valid commands: setup, run, stats, review, reset, retry, search, apply, interview")
        sys.exit(1)

if __name__ == "__main__":
    main()