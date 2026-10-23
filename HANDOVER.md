# LinkedIn Boss v2: handover (session of 22–23 Oct 2026)

## Where things stand

- **v2 is the current system, committed locally on `master`** (not pushed). v1 lives on only in git history (commit `f64fdf4`).
- **Nothing has run live yet.** The build machine had no network access to LinkedIn, the application systems or Gemini. Everything passed offline tests (below). The first real run must be a dry run.

## What the v1 data showed (applications.db, Jan–Apr 2026)

- **Funnel:** 4,262 jobs scraped → 2,332 approved by the AI → **1,464 submitted** → 2 interviews.
- **Failures:**
  - 527 errors, 513 of them "Easy Apply modal didn't load".
  - 198 "no Easy Apply button".
  - 210 manual review.
- **The evaluator approved 55% of jobs at an average 88% confidence.** It rated a "5+ yrs C++" role at 90% against 2–3 real years. The prompt was permissive and fed the CV's own superlatives back.
- **Targeting was scattered:**
  - 40 keywords, from CTO to Technical BA.
  - About 330 applications went to recruitment agencies, 43 of them to Hays.
  - 112 company + title combinations were applied to more than once (reposts).
- **About 55% of submissions were Australian roles**, mostly hybrid.
- **Only 31 of 4,262 scraped jobs were graphics/3D/CV/XR/audio**, Simon's strongest niche.
- **Both saved replies (Arju, Sam) were people contacting Simon**, not responses to applications.

**Simon's decisions:** keep the volume approach and fix it. Add more application systems. Target all role types: Graphics/3D/CV/XR, Applied AI/LLM, Platform/Solutions architecture, Engineering leadership, plus **Forward Deployed Engineer**. Locations: NZ + AU + global remote. Contract and permanent equally. "Go where the money is", so the queue is sorted by pay.

## Root cause of v1's biggest failure

Since January 2026, LinkedIn's job page renders Easy Apply inside a hidden full-screen iframe (`iframe[data-testid="interop-iframe"]`). The Easy Apply button is now `<a data-view-name="job-apply-button" aria-label="Easy Apply to this job" href=".../apply/?openSDUIApplyFlow=true">`. v1 waited for `[role=dialog]` in the main frame and timed out. v2 scans every frame.

## What v2 is (see README.md and CLAUDE.md for the full map)

- **`src/services/form_engine/`: a generic form engine.**
  - `dom_scan.js` finds fields, buttons and errors by label/role in every frame and in open shadow DOM.
  - `engine.py` fills fields with real interactions and reads the values back.
  - `matching.py` does option matching.
  - `answerer.py` answers in this order: EEO decline → consent → `APPLICATION_PROFILE` (new, in `cv_data.py`) → answer bank → Gemini (short batch + long-form + cover letters).
- **`src/services/appliers/`: the appliers.**
  - `base.py` (`FormRunner`) runs the step loop: validation → AI fix → human gate; vision assist when stuck.
  - `linkedin.py` handles Easy Apply (iframe-aware) and follows external Apply buttons.
  - `external.py` covers Greenhouse, Lever, Ashby, Workday (sign-in/create account via `ATS_ACCOUNT_EMAIL/PASSWORD`), SEEK, SmartRecruiters, Workable, JobAdder, PageUp and others, plus a generic fallback.
- **`answer_bank.py`:** saved answers. AI answers are saved only after a successful submit. Answers that failed validation are dropped. Edits Simon makes before submitting are saved as approved. Review them from menu option 12.
- **`documents.py`:**
  - picks the CV per lane (`CV_FILES` in `config.py`)
  - feeds the uploaded CV's text to the AI
  - writes cover letters as `.docx`
- **`browser.py`:** persistent Chrome profile in `data/browser_profile`. The legacy cookies are imported on first run.
- **`job_scraper.py`:**
  - search plan is lanes × locations, rotated through `search_log`
  - not Easy-Apply-only
  - contract + permanent
  - parses cards from both the `/jobs/view/<id>` and `currentJobId=` formats
- **`job_evaluator.py`:**
  - reads the description, apply type and pay
  - Gemini returns lane, eligibility, blockers and a pay estimate
  - pay is normalised to annual NZD
  - the confidence threshold is enforced
  - reposts are skipped
- **`ai_service.py`:** model chains per role (`MODELS` in config) with fallback; retries 429/5xx.
- **`migrate_db.py` → `apply_v2`:** idempotent, runs at startup. It adds columns, the `search_log` table, the `answer_bank` table, and normalises v1 titles.
- **`main.py` menu:** new options 12 (answer bank), 13 (external queue), 14 (doctor) and 15 (capture).
- **`config.py`:** new settings for lanes, locations, `EASY_APPLY_ONLY=False`, `EXTERNAL_AUTO_SUBMIT` per system (off for Workday/SEEK/PageUp/generic), `MENTION_APPLICATION_BOT=False`, `EEO_POLICY`, `QUEUE_MAX_AGE_DAYS`, `FX_TO_NZD`.

## Independent review (18 defects, all fixed, covered by `tests/test_regressions.py`)

- **Critical (all fixed):**
  - vision assist could click submit-type buttons (now only non-risky next/other buttons)
  - consent rule ticked "I confirm I'm authorised to work in the US"-type declarations
  - "Apply"/"Apply with LinkedIn" were classed as submit buttons
  - upload-hint text ("Attach a .pdf") was read as an attached file, so the CV was never uploaded
- **Others:**
  - the LinkedIn review step lost its Submit button when it had no fields
  - "Applied AI Engineer" was treated as already applied
  - confidence threshold was ignored
  - evaluation could loop forever with `EXTERNAL_APPLY=False`
  - Gemini errors rejected jobs permanently
  - a single 400 error disabled every model
  - the login check always passed (`\b` in a non-raw string)
  - wrong phone format when the country code was preselected
  - the bank learned answers Simon had corrected
  - Windows `:` appeared in filenames
  - dry runs consumed the queue
  - Simon's own phone/name went into "extension"/"referrer" fields
  - `maxlength=-1` was mishandled
  - `--easy-only` was ignored
  - the frame filter was too broad

## Tests (offline, mocked Gemini; all pass)

```
python tests/test_engine.py
python tests/test_engine_linkedin.py data/debug_html/*.html
python tests/test_linkedin_flow.py
python tests/test_external_flow.py
python tests/test_regressions.py
```

## Verified live (23 Oct 2026)

1. **Packages:** Playwright 1.64, google-genai 2.32; tests launch installed Chrome (`channel="chrome"`).
2. **Doctor / models:** every `MODELS` chain resolves to its first choice. The old Gemini key was dead; the working key comes from `E:\deepPBR.io\.env`.
3. **Login detection:** LinkedIn has two headers (classic `.global-nav__me` on job search, `data-testid="primary-nav"` on feed/jobs home); falls back to the `li_at` cookie.
4. **Scraper:** all five locations (both geoIds correct). Fixed: the card reader now uses the whole `li[data-occludable-job-id]` card, so footer badges (Easy Apply / Applied / Promoted) are seen.
5. **Easy Apply:** the form is a native `<dialog open data-testid="dialog">` in the main frame (no iframe, no `role="dialog"`). Fixed and verified end to end in dry run: steps advance, existing LinkedIn resume kept, follow box unticked. Also fixed: labels from group context (no "This field is required" labels), work-history/education editors never AI-filled (needs human), Yes/No radios whose question is a shared `aria-label`, React re-renders dropping `data-lb-*` tags, dry runs no longer write results.
6. **Cost:** answer cache (`ai_cache` table), Gemini context cache for stable system prompts, low thinking level.

## Not verified yet

1. **External systems live** (`apply <url>` with a Greenhouse, Lever and Ashby posting): confirm React-select comboboxes, the location autocomplete, Ashby yes/no toggles, and the email-verification-code gate. Workday and SEEK are the least tested. Until then run with `--easy-only`.
2. **When something breaks:** `python src/main.py capture`, then inspect `data/fixtures/<timestamp>/`, fix the JS, and add a fixture test.

## Open items and decisions for Simon

- **Public repo.** `src/services/cv_data.py` (phone, accessibility details) is committed to `github.com/thesystemera/LINKEDIN_BOSS`. If that repo is public, consider making it private or untracking `cv_data.py` before pushing v2.
- **Outdated CV text.** `CV_FULL_TEXT` in `cv_data.py` is the older "Creative Technologist" CV. The bot now passes the *uploaded* CV's text (`CV_FILES`) to the AI, so answers match what employers see. It's worth making `CV_FULL_TEXT` match too.
- **Bot mentions.** `MENTION_APPLICATION_BOT=False` stops cover letters from saying the application was AI-optimised (v1 allowed it).
- **Rough numbers in config.** FX rates and work-days-per-year in config are approximations, used only for pay ranking.
