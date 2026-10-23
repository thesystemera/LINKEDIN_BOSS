# CLAUDE.md

Guidance for AI coding agents working in this repository.

## Project

LinkedIn Boss v2: scrapes LinkedIn jobs (Easy Apply and external postings), evaluates them with Gemini, and fills/submits
applications on LinkedIn Easy Apply and external application systems (Greenhouse, Lever, Ashby, Workday, etc.).
The owner runs it on Windows from PyCharm (`src/main.py`, default command `run`) with a `.venv`. No test suite beyond `tests/`
(offline Playwright tests against fixtures); validate changes with `python src/main.py run --dry-run` or `apply <url>` with approval.

## Run

```bash
python src/main.py            # menu
python src/main.py doctor     # key, models, CVs, browser
python src/main.py setup      # log in inside the bot's persistent browser profile (data/browser_profile)
python src/main.py run [--dry-run|--no-approval|--easy-only]
python src/main.py apply <linkedin url|job number|any application url>
python src/main.py answers | external | capture | stats | retry | search | review | interview
```

## Pipeline

1. `JobScraper` – LinkedIn search URLs built from `SEARCH_LANES` × `SEARCH_LOCATIONS` (config), rotated via `search_log`.
   Cards are parsed by JS (`CARDS_JS`) that keys on `/jobs/view/<id>` and `currentJobId=<id>` links, not CSS classes.
2. `JobEvaluator` – opens each job, extracts description/apply type/pay (`DETAILS_JS`, `JOB_STATE_JS`), Gemini returns
   apply/confidence/lane/eligibility/blockers/pay. Pay is normalised to annual NZD (`FX_TO_NZD`). Volume strategy: permissive,
   but hard blockers (location-restricted remote, clearance, citizenship) reject.
3. Apply – queue ordered by pay (`SORT_QUEUE_BY_PAY`), stale jobs (`QUEUE_MAX_AGE_DAYS`) and reposts (`REPOST_COOLDOWN_DAYS`) skipped.
   - `LinkedInApplier.easy_apply` – the Easy Apply form usually renders inside LinkedIn's interop **iframe**; everything is frame-aware.
   - `LinkedInApplier.external_apply` – clicks Apply, captures the new tab, hands it to `ExternalApplier`.
   - `ExternalApplier` – detects the system (`detect_ats`), runs `_prep_<ats>` (apply buttons, Lever `/apply`, Ashby `/application`,
     Workday sign-in/account via `ATS_ACCOUNT_EMAIL/PASSWORD`), then the shared `FormRunner`.
     `EXTERNAL_AUTO_SUBMIT[ats]` decides whether auto mode may submit; otherwise it stops for a human.

## Form engine (`src/services/form_engine/`)

- `dom_scan.js` runs in every frame and returns fields (kind, label, question, options, value, required, errors) and buttons
  (kind: next/review/submit/apply/back/close/done/other). It tags elements with `data-lb-fid` / `data-lb-opt` / `data-lb-bid`;
  Python targets those attributes. Pierces open shadow DOM. `strictRoot` (LinkedIn) ignores frames without the apply dialog.
- `engine.py` fills with real Playwright interactions and reads values back (`READ_VALUE_JS`); comboboxes are opened and
  options read from the nearest visible listbox (`OPTIONS_JS`).
- `answerer.py` order: EEO decline → consent/marketing checkboxes → `APPLICATION_PROFILE` facts → answer bank → Gemini
  (`ShortAnswers` batch per page, `LongAnswers` with the pro model, cover letters). AI answers go to `ctx["bank_pending"]` and are
  committed to the bank only when the application succeeds; answers that fail validation are discarded/demoted.
- `appliers/base.py` `FormRunner` loop: scan → fill pass (up to 3 passes for conditional fields) → submit (approval) or next/review →
  validation errors → AI fix once → human gate (manual mode) or `manual_review_needed`. Vision assist when no button is recognisable.

## Rules

- **Single source of truth**: profile data only in `src/services/cv_data.py` (`CV_SUPPLEMENTARY`, `CV_FULL_TEXT`, `APPLICATION_PROFILE`).
  The uploaded CV text (`documents.cv_text`) is passed to the AI so answers match what the employer sees.
- **Truthful answers**: never invent experience, employers, addresses, IDs. Required fields with no grounded answer → human.
- **Never auto-submit by accident**: only `FormRunner.approve()` may lead to clicking a `submit`-class button; vision assist may only
  click non-risky `next`/`other` buttons (`RISKY_BTN_RE`). Declarations about work rights, clearance, licences etc. are never auto-ticked.
- **Fail loud**: log every skipped/failed field; save `data/debug_html/*.html|png` on failures (`save_debug`).
- **Schema changes** go in `migrate_db.py` (`apply_v2` is idempotent and runs at startup). Query helpers live in `database.py`.
- **Models** are role chains in `settings.MODELS` (`eval`, `forms`, `pro`, `lite`, `vision`); `AIService` falls back down the chain on
  404/deprecation and retries 429/5xx. Use `AIService().structured(prompt, PydanticModel, role=..., system=...)`.
- **Cost**: put stable text (instructions, CV/candidate data) in `system=` and only the per-job part in `prompt`. The system
  prompt goes into a Gemini context cache (`AI_EXPLICIT_CACHE`), identical requests are answered from the `ai_cache` table
  (`AI_RESULT_CACHE`, bump `AI_CACHE_EPOCH` to invalidate), and `THINKING_LEVEL` keeps thinking tokens low (same approach as deepPBR).
- Keep delays random (`random.uniform`); keep `HEADLESS = False`.
- When LinkedIn markup changes: run `python src/main.py capture`, inspect `data/fixtures/<timestamp>/`, adjust the JS in
  `job_scraper.py` / `job_evaluator.py` / `appliers/linkedin.py` / `dom_scan.js`, and add a fixture test under `tests/`.

## Tests

```bash
python tests/test_engine.py            # synthetic ATS form: every field kind
python tests/test_engine_linkedin.py data/debug_html/*.html
python tests/test_linkedin_flow.py     # multi-step Easy Apply inside an iframe, mocked Gemini
python tests/test_external_flow.py     # external form twice: second run must reuse saved answers
python tests/test_regressions.py       # safety regressions: button classes, declarations, file hints, dry run, cards, login
python tests/test_ai_cache.py          # AI answer cache and thinking settings, mocked Gemini
```

## Interview assistant

`src/services/interview_*.py` – unchanged from v1 (two-tier sentinel/advisor, Whisper audio, high-contrast display).
