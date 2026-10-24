# LinkedIn Boss v2: handover (updated 24 Oct 2026)

## Where things stand

- **v2 runs live and fully automatic** (`python src/main.py run --no-approval`): Easy Apply plus external systems, auto-submit on, 40 applications a day (`MAX_APPLICATIONS_PER_DAY`).
- **Results since 23 Oct:** 46 confirmed submissions (36 Easy Apply, 7 Greenhouse, 2 generic, 1 Workable), 11 submitted but unconfirmed, 96 stopped for a human, 5 errors. v1 plus v2 all-time: 1,510 confirmed.
- **AI provider:** Gemini's prepaid credit ran out on 24 Oct. With `AI_PROVIDER = "auto"` the bot switches to Claude on the first 402 for the rest of the run (key `CLAUDE_API_KEY` in `.env`, about $200 of Console credit). The run of 24 Oct afternoon is on Claude.
- **Code:** `master` on `github.com/thesystemera/LINKEDIN_BOSS` (**public**). Secrets and personal files stay out of git: `.env`, `data/` (database, browser profile, `private_profile.json` with the street address, `cv_variants/`, debug snapshots, logs).

## AI and cost

- **Roles** (`settings.MODELS` for Gemini, `settings.CLAUDE_MODELS` for Claude):
  - `eval`, `forms`, `lite`, `vision`: Gemini Flash(-Lite) / Claude Sonnet 5.5. A side-by-side check on 7 real jobs found Haiku rejected good remote fits; Sonnet is about 1 cent per job evaluation.
  - `pro` (cover letters, long answers, CV variants): Gemini Pro / Claude Opus 5.5, about 8 cents per cover letter. Opus always thinks (no thinking setting is sent; effort keeps it short) and gets 4,000 extra output tokens for it.
- **Cost layers, both providers:**
  - identical requests come from the `ai_cache` table;
  - the stable system prompt (instructions + CV) is cached: a Gemini context cache, or a Claude `cache_control` breakpoint (74% of input at the cached rate in testing);
  - thinking is low or off.
  - The run prints a usage line at the end, with a dollar estimate for Claude.
- **Claude rules:** the 5.5 models reject `temperature` (it is never sent). JSON output goes through `output_config.format`; a schema Claude rejects falls back to plain JSON mode. Thinking is off where the model allows it: `disabled` on Haiku, `between_tools` on Sonnet.
- **CV facts:** the PLAiR lines in `CV_FULL_TEXT` were corrected on 24 Oct (Gemini/DeepSeek, ~33k embeddings with Annoy, 75+ services). Since the same day the bot uploads the tailored CVs (`USE_TAILORED_CVS = True`, `data/cv_variants/<lane>/Simon_Che_de_Boer_CV.docx`, approved by Simon); the older CVs in `Data/` still carry the old claims (Claude, pgvector 1M+) and are only a fallback.
- `CONFIDENCE_THRESHOLD = 40`, the evaluation prompt's own apply rule. Claude scores lower and more realistically than Gemini did, so 50 would have cut volume.

## Biggest gaps (next work, ranked by lost applications since 23 Oct)

1. **Generic sites, "complex form - couldn't progress" (39).** Mostly gig/aggregator sites and unknown applicant systems. Look at `data/debug_html/<time>_<company>_<job>.html|png` for each. The `FormRunner` loop gives up when no next/submit button is recognised and vision assist finds nothing safe to click.
2. **Account walls (Workday 12, iCIMS 5, SmartRecruiters 2, SuccessFactors 1).** Workday sign-in/account creation exists (`_prep_workday`, `ATS_ACCOUNT_EMAIL/PASSWORD`) but stalls; SuccessFactors has no account flow.
   - **iCIMS (24 Oct):** `_prep_icims` / `_icims_signin` handle Jibe career sites (`jibeapply.com`, e.g. GitHub). The application lives in a slow cross-site iframe that the old scan missed, so it is opened as the page itself; then email + privacy consent, sign-in or new account, and the form runner. Fixture-tested end to end.
   - **Live on GitHub:** an hCaptcha image challenge appears after the email step, and captchas are never solved by the bot. Such jobs end as manual review ("solve the captcha"). Run `python src/main.py retry` with approval on (not `--no-approval`) to do them by hand; the sign-in and account steps after the captcha are not yet verified live. Each company has its own iCIMS portal, so a login does not carry over.
3. **External page did not open (7):** the Apply click opened nothing the bot caught (popup blocked, same-tab navigation, or a LinkedIn interstitial).
4. **Questions the profile can't answer:** notice period, "current or former employee of …", employment agreements, "Which ones?". They sit in the answer bank as `unanswered`; `python src/main.py answers` asks them first, and the answers then apply to every later form.
5. **Easy Apply work-history dates (6):** fixed on 24 Oct (`fill_known_work_dates`, Media Sculpt dates from `APPLICATION_PROFILE["work_history_dates"]`). Confirm in the next run.

Fixed on 24 Oct with fixture tests (`tests/test_regressions.py`):

- JobAdder phone boxes: the scanner took select2's hidden flag-picker inputs for the phone field.
- Location dropdowns without New Zealand: the bot now picks "Other …"; a state list without NZ goes to the bank / AI.
- Fuzzy option matching turned "New Zealand" into "Netherlands".
- Ashby (Dovetail): the bot gave up ~9 s after Submit while the button was still spinning; it now waits while the submit button stays disabled (`SUBMIT_WAIT_SECONDS`).
- Rippling (Copado, Abby Health): the upload hint "(.doc / .docx / .pdf)" was read as an attached CV, so the required CV was never uploaded.
- Decline answers now match each site's own wording ("I don't wish to answer", "Prefer not to say").

## Continuing in another session

- **Local session (this PC):** has everything: browser profile with the LinkedIn login, `.env` keys, database, snapshots. Start with `python src/main.py doctor`, then the newest `data/logs/YYYY-MM-DD.log`.
- **Cloud session (GitHub repo only):** no LinkedIn login, no keys, no database, no snapshots (all git-ignored, partly personal). Good for code work with the offline tests (all mocked). Not good for anything live or for the snapshot-driven fixes above unless a trimmed, de-personalised fixture is committed first.
- **Pending decisions for Simon:**
  - realityvirtual title, currently "Founder & CTO";
  - whether to skip gig/aggregator sites outright.

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

## Tests (offline, mocked AI; all pass on 24 Oct)

```
python tests/test_engine.py
python tests/test_engine_linkedin.py data/debug_html/*.html
python tests/test_linkedin_flow.py
python tests/test_external_flow.py
python tests/test_regressions.py
python tests/test_ai_cache.py         # answer cache, thinking settings, Gemini -> Claude switch
```

## Verified live (23 Oct 2026)

1. **Packages:** Playwright 1.64, google-genai 2.32; tests launch installed Chrome (`channel="chrome"`).
2. **Doctor / models:** every `MODELS` chain resolves to its first choice. The old Gemini key was dead; the working key comes from `E:\deepPBR.io\.env`.
3. **Login detection:** LinkedIn has two headers (classic `.global-nav__me` on job search, `data-testid="primary-nav"` on feed/jobs home); falls back to the `li_at` cookie.
4. **Scraper:** all five locations (both geoIds correct). Fixed: the card reader now uses the whole `li[data-occludable-job-id]` card, so footer badges (Easy Apply / Applied / Promoted) are seen.
5. **Easy Apply:** the form is a native `<dialog open data-testid="dialog">` in the main frame (no iframe, no `role="dialog"`). Fixed and verified end to end in dry run: steps advance, existing LinkedIn resume kept, follow box unticked. Also fixed: labels from group context (no "This field is required" labels), work-history/education editors never AI-filled (needs human), Yes/No radios whose question is a shared `aria-label`, React re-renders dropping `data-lb-*` tags, dry runs no longer write results.
6. **Cost:** answer cache (`ai_cache` table), Gemini context cache for stable system prompts, low thinking level.

7. **External systems (24 Oct):** Greenhouse, Workable and generic forms submit end to end; LinkedIn's "Share your profile?" link, the Easy Apply daily limit (Easy Apply deferred to tomorrow, external continues), guest/social sign-in buttons (never clicked) and the Lever location autocomplete are handled.
8. **Claude provider (24 Oct):** the automatic switch on Gemini's 402, every response schema the bot uses, prompt caching and evaluation quality were checked against the live API.

## When something breaks

`python src/main.py capture`, then inspect `data/fixtures/<timestamp>/`, fix the JS, and add a fixture test. Failed external applications also save `data/debug_html/*.html|png`.

## Other notes for Simon

- **Public repo.** `src/services/cv_data.py` (phone, work history) is public on GitHub. The street address lives only in the git-ignored `data/private_profile.json`.
- **Outdated CV text.** `CV_FULL_TEXT` in `cv_data.py` is the older "Creative Technologist" CV. The bot now passes the *uploaded* CV's text (`CV_FILES`) to the AI, so answers match what employers see. It's worth making `CV_FULL_TEXT` match too.
- **Bot mentions.** `MENTION_APPLICATION_BOT=False` stops cover letters from saying the application was AI-optimised (v1 allowed it).
- **Rough numbers in config.** FX rates and work-days-per-year in config are approximations, used only for pay ranking.
