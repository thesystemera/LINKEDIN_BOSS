# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

LinkedIn Auto-Apply automation bot that scrapes LinkedIn Easy Apply jobs, evaluates them with Gemini AI, and automatically submits applications. Targets 200-250 applications over 30 days with ~70% success rate.

**CRITICAL**: This violates LinkedIn's TOS. Risk of account ban exists but is mitigated through rate limiting and human-like behavior.

## Running the Application

### First-Time Setup
```bash
# Install dependencies
pip install -r requirements.txt
playwright install chromium

# Add Gemini API key
mkdir -p src/keys
echo "YOUR_KEY" > src/keys/gemini_key.txt

# Login to LinkedIn (save session)
python src/main.py setup
```

### Daily Operation
```bash
# Interactive mode (recommended)
python src/main.py

# Direct commands
python src/main.py run          # Run automation pipeline
python src/main.py stats        # View statistics
python src/main.py review       # List jobs needing manual review
python src/main.py reset        # Clear database
```

### Database Migrations
```bash
python migrate_db.py
# [1] Add description column to jobs table
# [2] Clean dirty URLs (removes query params, merges duplicates)
```

### No Tests
This project has no test suite. Testing is done manually via dry runs.

## Architecture & Data Flow

### Pipeline Stages (Sequential)
1. **Job Scraping** → 2. **AI Evaluation** → 3. **Application Submission**

Each stage outputs to the next stage and logs to SQLite database.

### Multi-Location Search Strategy
- Searches **multiple locations** sequentially (New Zealand, Melbourne)
- **Deduplicates** by URL across all searches
- Combines results before evaluation phase
- URL format: `https://www.linkedin.com/jobs/search/?f_AL=true&f_TPR=r604800&geoId={geo_id}&keywords={keywords}`

### Two-Stage AI Form Filling
**CRITICAL COST OPTIMIZATION**: All form fields are sent to Gemini in ONE batch call, not per-field.

1. **Stage 1 (Flash)**: Triage all fields, answer simple ones, flag complex ones
2. **Stage 2 (Pro)**: Only called if complex fields exist (cover letters, essays)

This reduces API costs from ~$0.50/month to ~$0.02/month.

**IMPORTANT**: Both stages now receive job descriptions for context (fixed as of 2026-01-07)

### Async/Sync Hybrid Pattern
- **Playwright**: Synchronous API (sync_playwright)
- **Gemini AI calls**: Async (asyncio + google-genai)
- **Bridge**: `nest_asyncio.apply()` in main.py allows `asyncio.run()` from sync context

**IMPORTANT**: Always use `asyncio.run()` for AI calls, never manually create event loops (nest_asyncio handles nesting).

### Session Management
- LinkedIn cookies saved to `data/linkedin_session.json` after first login
- Session reused across runs (no re-login needed)
- Session expires after ~30 days or if LinkedIn forces logout
- `session_manager.py` handles save/load via Playwright context

### Database Schema
**SQLite** (`data/applications.db`) with 4 tables:
- `jobs`: Scraped job data (title, company, URL, **description**, scraped_at)
- `evaluations`: AI decisions (job_id, **apply**, **confidence**, **reason**)
- `applications`: Submission results (job_id, status, error_message, steps)
- `daily_stats`: Daily application counts (date, applications_count)

**Deduplication**: Jobs table has UNIQUE constraint on URL - prevents re-processing same job.

**NEW (2026-01-07)**: Description column added to jobs table. Job descriptions are now:
1. Extracted during evaluation
2. Saved to jobs table
3. Passed to AI for cover letter generation

### Data Format Consistency (CRITICAL - Bug Fix 2026-01-07)

**THE BUG**: Code was crashing with `KeyError: 'evaluation'` when applying to jobs from database.

**ROOT CAUSE**: Inconsistent data formats:
- `job_evaluator.py` creates: `job['evaluation'] = {'confidence': X, 'reason': Y, 'apply': True}` (NESTED)
- `database.py` returned: `job['confidence'], job['reason']` (FLAT)
- `main.py` expected: `job['evaluation']['confidence']` (NESTED)

**THE FIX**: Database now transforms to nested format when retrieving jobs.

**Database stores FLAT** (separate columns):
- `evaluations.confidence`, `evaluations.reason`, `evaluations.apply`

**Code uses NESTED everywhere** (dict structure):
- `job['evaluation'] = {'confidence': X, 'reason': Y, 'apply': True}`

**Transformation in `database.py`** (lines 304-322):
```python
job = {
    'id': row['id'],
    'title': row['title'],
    'company': row['company'],
    'url': row['url'],
    'description': row['description'],
    'evaluation': {  # ← Transform flat to nested
        'confidence': row['confidence'],
        'reason': row['reason'],
        'apply': row['apply']
    }
}
```

**Result**: `main.py` always uses `job['evaluation']['confidence']` regardless of source.

**NO MIGRATION NEEDED** - database schema unchanged, only read-time transformation.

## Critical Configuration (config.py)

### Gemini Models (2025-2026)
```python
GEMINI_MODEL_EVAL = "gemini-2.5-flash"   # Job evaluation
GEMINI_MODEL_FORMS = "gemini-2.5-flash"  # Form field triage
GEMINI_MODEL_COVER = "gemini-2.5-pro"    # Cover letters only
```

**DO NOT** use outdated models (gemini-1.5-*, gemini-2.0-*). User requires 2.5+ series.

### Anti-Ban Rate Limiting
```python
MAX_APPLICATIONS_PER_DAY = 100          # Hard limit
MIN_DELAY_BETWEEN_APPS = 5              # 2 minutes (seconds)
MAX_DELAY_BETWEEN_APPS = 15             # 6 minutes (seconds)
JOB_READ_TIME_MIN/MAX = 3-7 seconds     # Simulates human reading
HEADLESS = False                         # MUST be False (visible browser looks human)
```

**NOTE**: User has aggressive settings (100/day). These are proven safe for their use case.

### Search Mode Settings
```python
USE_SEARCH_MODE = True                   # True = search, False = recommendations
SEARCH_LOCATIONS = ["New Zealand", "Melbourne"]
SEARCH_DATE_FILTER = "r604800"          # Past week (r86400=24h, r2592000=month)
SEARCH_KEYWORDS = ["software architect", "solutions architect"]
```

**Location cycling**: System searches all locations, deduplicates, then evaluates.

## Single Source of Truth: cv_data.py

**CRITICAL PRINCIPLE**: `src/services/cv_data.py` is the **SINGLE SOURCE OF TRUTH** for all user profile/CV data.

### What Lives in cv_data.py

**CV_SUPPLEMENTARY** (structured dictionary):
- `role_preferences`: Preferred role levels (soft guidance, not hard requirements)
- `salary_strategy`: Compensation expectations and strategy
- `target_locations`: Geographic preferences
- `background_context`: Full origin story (child prodigy, BBS at 11, early tech journey)
- `technology_experience_years`: Professional work experience timelines for each tech
- `supplementary_skills`: Skills not formally listed on CV
- `supplementary_experience`: Additional context (music, fire story, meta-automation)
- `contact_details`: Name, email, phone, location
- `residency_status`: Work authorization, sponsorship needs
- `profile_links`: LinkedIn, GitHub, portfolio URLs

**CV_FULL_TEXT** (formatted resume):
- Full professional CV as markdown text
- Used by AI for general context and evaluation

### SSOT Rules

✅ **DO:**
- Import CV_SUPPLEMENTARY and CV_FULL_TEXT from cv_data.py in all services
- Pass CV data to AI prompts (don't rewrite it)
- Update cv_data.py when user's profile/experience changes
- Keep prompts simple - let the data be rich

❌ **DON'T:**
- Duplicate profile data in config.py or other files
- Hardcode user preferences/requirements in prompts
- Create separate "user profile" dictionaries elsewhere
- Override cv_data with prompt-level instructions

### User Profile Summary
- **Creative Technologist** with VR/AR/AI/ML background
- Former CTO of 11-person VR studio (Lumiere Award, Forbes featured, TEDx speaker)
- Child prodigy: Started company at 9, built BBS at 11, coding since early 90s
- Expert in: Python, React, FastAPI, GLSL shaders, ML/AI, audio processing
- Built PLAiR (60+ microservices), MoneyPrinter (hedge fund-level predictions)
- 10+ years professional experience, 35+ years total tech immersion
- Open to: Staff/Principal/Lead roles, strong Senior roles at great companies
- Locations: New Zealand, Melbourne, Remote (AU/NZ)

### Supplementary Data (Meta Humor)
The user has added meta-automation context to supplementary_experience:
```python
"meta_automation": {
    "context": "Built custom AI-powered job application system (Playwright + Gemini) that extracts form fields, generates contextual answers, and optimizes application throughput. Because why apply to jobs manually when you can architect a solution?",
    "relevance": "Demonstrates end-to-end automation thinking, AI orchestration, and the kind of 'scratch your own itch' engineering philosophy that drives innovation"
}
```

This is available to AI for context and may appear in cover letters as a legitimate flex.

## LinkedIn Selector Updates

LinkedIn frequently changes HTML structure. Current selectors (as of 2026-01-07):

### Job Cards (Search/Recommendations)
**CRITICAL FIX (2026-01-07)**: LinkedIn changed structure - must find link element FIRST, not title container div.

```python
# CORRECT (job_scraper.py:117-120)
link_elem = card.query_selector('a.job-card-list__title--link') or card.query_selector('a.job-card-container__link')
title_elem = link_elem if link_elem else card.query_selector('.artdeco-entity-lockup__title')
company_elem = card.query_selector('.job-card-container__primary-description, .artdeco-entity-lockup__subtitle')
```

**WRONG** (old code that broke):
```python
# This finds the CONTAINER div, not the link!
title_elem = card.query_selector('.artdeco-entity-lockup__title')
link_elem = title_elem  # ❌ Div has no href attribute
```

**HTML Structure**:
```html
<div class="artdeco-entity-lockup__title">  <!-- OLD CODE STOPPED HERE -->
    <a class="job-card-list__title--link" href="...">  <!-- NEW CODE GETS THIS -->
        <strong>Job Title</strong>
    </a>
</div>
```

### Easy Apply Modal
```python
easy_apply_button = 'button:has-text("Easy Apply")'
next_button = 'button[aria-label*="Continue"], button:has-text("Next")'
submit_button = 'button[aria-label*="Submit application"]'
review_button = 'button[aria-label*="Review"]'
close_button = 'button[aria-label*="Dismiss"]'
```

### URL Cleaning (CRITICAL)
LinkedIn appends tracking parameters that change between searches:
```
https://www.linkedin.com/jobs/view/4346719111/?eBP=CwEAAA...&trackingId=...&refId=...
```

We strip everything after `?` to get canonical URL:
```python
url = url.split('?')[0]  # https://www.linkedin.com/jobs/view/4346719111/
```

**Why**: Without cleaning, same job appears multiple times with different tracking params, causing duplicates.

**When selectors break**: Check `src/page_structure/` for saved HTML, analyze structure, update selectors.

## Manual Approval Mode

**Default behavior**: `MANUAL_APPROVAL = True`
- System asks "Submit this application? (y/n/v)" before each submit
- `v` = view filled form in browser before deciding
- `n` = skip this job
- User can also set `DRY_RUN = True` to stop before clicking submit button

## File Structure Notes

### API Keys Location
- **MUST** be in `src/keys/gemini_key.txt` (NOT server/keys)
- Path: `Settings.KEYS_DIR / "gemini_key.txt"`
- Loaded via: `settings.load_api_key_from_file("gemini_key")`

### Services Consolidation
- All services are in `src/services/`
- No duplicate services in server/ directory
- server/ folder is legacy and should be ignored

### Page Structure Dumps
- `src/page_structure/` contains saved LinkedIn HTML pages for debugging
- When LinkedIn structure changes, save current page HTML here
- Analyze HTML to update selectors before modifying code

### Debug HTML (Auto-Captured)
- `data/debug_html/` contains modal HTML auto-captured when validation errors occur
- Filename: `{timestamp}_{company}_{job_id}.html`
- Use job ID from logs to find matching HTML file
- Inspect to understand why field detection failed

## Error Handling Philosophy

**FAIL LOUD, NOT SILENT**

As of 2026-01-07, all errors are logged, NOT silently ignored:

```python
# job_scraper.py
if not (title_elem and company_elem and link_elem):
    custom_print("WARNING", f"Card {idx}: Missing elements - link={link_elem is not None}, ...")

if not url:
    custom_print("WARNING", f"Card {idx}: No URL found (link element has no href attribute)")

except Exception as e:
    custom_print("ERROR", f"Card {idx}: Failed to extract job data - {str(e)}")
```

**Why**: User discovered selector bug hours late because errors were silently caught. Now errors are immediately visible.

## Logging & Visibility

### Database Stats at Startup
Every run shows database status:
```
[INFO] Database: 70 jobs scraped, 70 evaluated, 35 applications submitted
[INFO] Application statuses: success: 30, manual_review_needed: 5
```

### Log Levels
- `SUCCESS`: Jobs found, applications submitted, operations completed
- `INFO`: Database stats, pipeline status, duplicate URLs
- `WARNING`: Missing elements, empty URLs, validation issues
- `ERROR`: Extraction failures, API errors, critical problems
- `DEBUG`: (use sparingly) detailed troubleshooting info

**User requirement**: Logs must be clear and actionable. No defensive programming that hides problems.

## Common Issues & Solutions

### "Cannot navigate to invalid URL"
- Job URLs from LinkedIn are relative (e.g., `/jobs/view/123/`)
- MUST prepend `https://www.linkedin.com` if URL doesn't start with `http`
- Check: `job_scraper.py` URL normalization code

### "RuntimeError: asyncio.run() cannot be called from a running event loop"
- Solution already implemented: `nest_asyncio.apply()` in main.py
- Always use `asyncio.run()` for async calls (don't manually create loops)

### "ModuleNotFoundError: No module named 'services'"
- Ensure all imports are relative to `src/` directory
- Path injection: `sys.path.insert(0, str(src_path))` at top of service files

### Session Expired
- Run `python src/main.py setup` again
- User will manually login in browser window
- New session saved automatically

### Scraper Finding 0 Jobs
**Recent Issue (2026-01-07)**: LinkedIn changed HTML structure.
- Check logs for `[WARNING] Card X: Missing elements` or `No URL found`
- Save current LinkedIn page HTML to `src/page_structure/`
- Analyze structure and update selectors in `job_scraper.py`
- **Current fix**: Find link element first, not container div

## Development Guidelines

### Configuration Consolidation Rules
- **CV/Profile data**: ONLY in `cv_data.py` (CV_SUPPLEMENTARY, CV_FULL_TEXT, supplementary)
- **Search settings**: ONLY in `config.py` (keywords, locations, filters)
- **Never duplicate** - if it's about the user's profile, it goes in cv_data.py

### When Updating Search Keywords
- User is Creative Technologist + Solutions Architect
- Target: Architecture, Leadership, Senior IC, Domain-specific (AI/ML/Graphics)
- Current keywords: "software architect", "solutions architect"
- AVOID: Java, .NET, DevOps, IT support, generic "engineer"
- Keywords should be actual job titles companies post, not academic terms

### When Adding New Gemini Calls
- Always use structured output with Pydantic schemas
- Use Flash model unless explicitly complex (only Pro for cover letters)
- Pass ALL form fields in ONE batch, not per-field
- **CRITICAL**: Always pass job description to form filling functions
- Temperature: 0.3 for most tasks (user preference)

### When Modifying Rate Limits
- User has aggressive settings (100/day) that work for their use case
- Changes should still be discussed
- Delays must be random (use `random.uniform()`)

### Database Changes
- Schema is simple by design - no ORM overhead
- All queries are raw SQL via sqlite3
- **ALWAYS add migrations** - users have existing data
- Use `migrate_db.py` for schema changes, NEVER modify database.py directly

## Interactive Mode Menu

When run without arguments, displays:
```
[1] Run automation (with manual approval)
[2] Run automation (auto mode - no approval)  # Requires confirmation
[3] Dry run (show what would happen, don't submit)
[4] Setup (login to LinkedIn)
[5] View statistics
[6] Review jobs needing manual attention
[7] Reset database (clear all data)
```

User typically uses option 1 (manual approval) or 3 (dry run for testing).

## Form Filling System (CRITICAL)

### LinkedIn Form Event Handling
**CRITICAL**: LinkedIn's forms use React/modern JavaScript that relies on DOM events to update internal state. Simply setting values via JavaScript **WILL NOT** trigger validation.

#### Required Event Dispatching Pattern
ALL form interactions MUST dispatch events for LinkedIn to recognize them:

```javascript
// Radio buttons
page.evaluate('''(el) => {
    el.click();
    el.dispatchEvent(new Event('change', { bubbles: true }));
    el.dispatchEvent(new Event('input', { bubbles: true }));
}''', element)
time.sleep(0.5)  // Give LinkedIn time to process validation

// Dropdowns
page.evaluate(f"(el) => {{
    el.selectedIndex = {idx};
    el.dispatchEvent(new Event('change', {{ bubbles: true }}));
    el.dispatchEvent(new Event('input', {{ bubbles: true }}));
}}", element)
time.sleep(0.5)

// Text fields - Playwright's .fill() handles this automatically
element.fill(answer)
```

**Why This Matters:**
- Without events: Form appears filled but LinkedIn thinks it's empty → validation fails → infinite loop
- With events: LinkedIn's event handlers update internal state → validation passes → form progresses
- `bubbles: true` ensures events propagate up to React's root listener
- 0.5s delay gives LinkedIn's JavaScript time to process validation

### Form Validation Error Detection
**CRITICAL**: After clicking Review/Next buttons, MUST check for LinkedIn validation errors or app will loop forever.

```python
# After clicking Review button
review_btn.click()
time.sleep(2)  # Give LinkedIn time to validate

# Check for visible error messages
error_messages = page.query_selector_all('[role="alert"], .artdeco-inline-feedback--error, [id*="error"]')
visible_errors = [err for err in error_messages if err.is_visible()]
if visible_errors:
    for idx, err in enumerate(visible_errors[:5]):
        err_text = err.inner_text().strip()
        custom_print("ERROR", f"  {idx+1}. {err_text[:100]}")
    return {"status": "manual_review_needed", "error": "Form validation failed", "steps": steps}
```

### AI Hallucination Filtering
Gemini sometimes generates extra fields not in the form. Filter answers to only valid field indices:

```python
answers = {}
for key, value in gemini_result.get('answers', {}).items():
    idx = int(key)
    if 0 <= idx < len(fields):  # Valid index only
        answers[idx] = value
```

**Philosophy**: "Just ignore hallucinations" - don't try to prevent them, just filter them out.

### Fail Fast Philosophy
**User's approach**: Better to fail fast than submit wrong application.

- If radio question text can't be extracted → return `None`, don't guess
- If field type unknown → skip it, don't make assumptions
- If validation fails → abort to manual review, don't keep trying
- If dropdown option doesn't match → warn and skip, don't pick random option
- **NO SILENT FAILURES** → always log warnings/errors

This prevents submitting applications with wrong information.

## Testing & Debugging

### Test Harness
`test_easy_apply.py` provides rapid iteration for form filling logic:

```bash
python test_easy_apply.py "https://www.linkedin.com/jobs/view/123456"
```

**Key Features**:
- Uses same FormFieldFiller service as production (not mocks)
- Stops at submit button for manual review
- Logs all field detection, AI calls, filling steps
- Shows validation errors before closing

### AsyncIO Warning (Ignorable)
```
RuntimeError: Leaving task does not match current task
```

This warning from `nest_asyncio` is safe to ignore. Tasks complete successfully despite the warning.

### Debug HTML Capture (Form Validation Errors)

When form validation fails, the system automatically saves the modal's HTML to `data/debug_html/` for inspection:

```
data/debug_html/
  20260129_143052_BAH_Partners_4363491965.html
  20260129_143215_ConnectedSolutions_4363472688.html
```

**Filename format**: `{timestamp}_{company}_{job_id}.html`

Each file includes a header with:
- Job title, company, URL
- Timestamp
- Error context (the validation error messages)

**How to use**:
1. Run automation, note which job numbers fail with validation errors
2. Check `data/debug_html/` for matching job ID
3. Open HTML file to inspect LinkedIn's actual field structure
4. Look for: `type=`, `inputmode=`, `pattern=`, `data-*` attributes
5. Update `form_field_filler.py` detection logic if needed

**Why this exists**: LinkedIn uses `type="text"` for numeric fields with JavaScript validation. We can't always detect numeric fields from HTML attributes alone. These captures help identify what attributes LinkedIn IS using so we can improve detection.

## Known Edge Cases

1. **Stale element references**: Always store element attributes (name, id), not elements themselves
2. **Duplicate IDs**: LinkedIn has invalid HTML - use `.query_selector_all()` and check visibility
3. **Covered elements**: Use JavaScript `.evaluate('el => el.click()')` instead of `.click()`
4. **Autocomplete delays**: Must wait for suggestions before selecting
5. **LinkedIn validation timing**: Forms need 1.5-2s after filling before clicking Next/Review

## Recent Critical Fixes

### 2026-01-29: Form Validation Fix + Debug HTML Capture

#### AI Fix Response Parsing Bug
**Problem**: When validation errors occurred, AI returned fixes but they were never applied.

**Root Cause**:
- AI returned: `[{"index": 0, "new_answer": "10.0"}, ...]` (raw list, different keys)
- Code expected: `{"answers": [{"field_index": 0, "answer": "..."}], "reasoning": "..."}`
- Line `result.get('answers', [])` failed on a list → `'list' object has no attribute 'get'`

**Solution** (`form_field_filler.py`):
- Handle both dict and list response formats
- Handle key variations: `index`/`field_index`, `answer`/`new_answer`
- Explicit JSON format in prompt to guide AI

#### Debug HTML Capture
**Problem**: No way to inspect LinkedIn's actual HTML when validation fails.

**Solution**: Auto-save modal HTML to `data/debug_html/{timestamp}_{company}_{job_id}.html` on any validation error. Includes job context and error messages in header comment.

**Files Changed:**
- `src/services/form_field_filler.py`: Fixed parsing, improved prompt
- `src/services/auto_applier.py`: Added `_save_debug_html()`, calls on all validation errors

### 2026-01-10: Multiple Critical Fixes

#### AI Prompt Philosophy Overhaul
**Problem**: Hardcoded seniority filters and rigid assumptions in prompts were rejecting good opportunities and hallucinating experience.

**Issues Found:**
1. **Hardcoded seniority gatekeeping**: Prompts explicitly said "Focus on Senior/Principal/Lead/Architect roles" and "Sell using Principal Engineer persona"
2. **Experience hallucination**: AI claimed "10 years C++ experience" when CV only showed 2-3 years indirect exposure via Unreal Blueprints
3. **Overly prescriptive rules**: 50+ edge-case rules trying to handle every scenario instead of letting AI be intelligent

**Solution: Data-Driven Approach**
- **Stripped prompts to 5 simple principles**: "Read cv_data, be honest, be smart"
- **Expanded cv_data.py with rich context**:
  - Added `background_context` with full origin story (child prodigy, started at 9, BBS at 11, 3D animation as teenager)
  - Added `technology_experience_years` with explicit professional work timelines
  - Added `role_preferences` (soft guidance, not hard requirements)
- **Removed all hardcoded filters**:
  - No more "only apply to Principal/Staff roles"
  - No more "Principal Engineer persona"
  - No more inferring years based on career length
- **Result**: AI makes intelligent decisions based on complete data, not rigid rules

**Files Changed:**
- `src/services/cv_data.py`: Expanded with background_context, technology_experience_years, role_preferences
- `src/services/form_field_filler.py`: FIELD_RULES reduced from 50 lines to 5 principles
- `src/services/job_evaluator.py`: Removed seniority filters, added flexibility ("open to strong opportunities at various levels")

**Philosophy**: Let the data be rich and complete. Let the AI be smart. Don't pigeonhole.

#### Validation Error Retry System
**Problem**: System detected validation errors ("Enter a whole number between 0 and 99") but immediately gave up instead of retrying with AI fix.

**Issues Found:**
1. **No retry logic**: `fix_validation_errors()` function existed but was NEVER called
2. **Decimal numbers in years fields**: AI answered "0.5 years" when LinkedIn expects integers
3. **Immediate bailout**: After detecting error, code would close modal and return "manual_review_needed" without attempting fix

**Solution: Intelligent Retry System**
- **Added config settings**:
  - `ENABLE_VALIDATION_RETRY = True` (can disable for testing)
  - `MAX_VALIDATION_RETRIES = 1` (one retry per page, total 2 attempts)
- **Retry flow**:
  1. Detect validation errors (already working)
  2. Extract error messages
  3. Call `fix_validation_errors()` with error context
  4. AI generates corrected answers
  5. Re-fill form with fixes
  6. Click Review again to re-validate
  7. If errors persist, give up (prevents infinite loops)
- **Integer enforcement**:
  - Added FIELD_RULES instruction: "For years questions, ALWAYS round to whole number"
  - Added safety in form filling code: detects "year" in label, rounds floats to integers
  - Example: "0.5" → "1", "1.7" → "2"

**Files Changed:**
- `src/config.py`: Added `ENABLE_VALIDATION_RETRY` and `MAX_VALIDATION_RETRIES`
- `src/services/auto_applier.py`: Wired up retry logic (lines 262-324)
- `src/services/form_field_filler.py`: Added rounding instructions and integer enforcement (lines 27-28, 630-636)

**Result**: Validation errors like "Enter a whole number between 0 and 99" are now automatically fixed instead of requiring manual intervention.

### 2026-01-07: Core System Fixes

### 1. Selector Bug Fix
**Problem**: LinkedIn changed HTML - old code found container div instead of link element.
**Solution**: Find link element FIRST, use it for both link and title.

### 2. Job Description Missing from AI
**Problem**: Cover letters were written with only job title + company (no description).
**Solution**:
- Added description column to jobs table
- Extract and save description during evaluation
- Pass description to both Flash and Pro AI models

### 3. Silent Error Handling
**Problem**: Errors were silently caught, making debugging impossible.
**Solution**: All errors now logged with WARNING/ERROR levels.

### 4. Database Visibility
**Problem**: User couldn't see database state at startup.
**Solution**: Show job counts and application statuses every run.

## TODO: Refactoring Needed

### Selector Consolidation (NOT COMPLETED)
Current state: Selectors scattered across multiple files (config.py, job_scraper.py, auto_applier.py, form_field_filler.py)

**Proposed**: Create `src/services/linkedin_selectors.py` with organized constants:
```python
JOB_SEARCH = {
    "job_cards": ".job-card-container, .jobs-search-results__list-item",
    "job_link": "a.job-card-list__title--link",
    "company": ".artdeco-entity-lockup__subtitle",
    # ...
}

BUTTONS = {
    "easy_apply": "button:has-text('Easy Apply')",
    "next": "button[aria-label*='Continue'], button:has-text('Next')",
    # ...
}

FORM_FIELDS = {
    "text_inputs": "input[type='text'], input[type='email'], ...",
    "radio_fieldset": "fieldset[data-test-form-builder-radio-button-form-component]",
    # ...
}
```

**Benefit**: Single source of truth for all LinkedIn selectors, easier to update when structure changes.

**Status**: Attempted but reverted due to selector bug unrelated to refactoring. Should be revisited.

## Interview Assistant

Real-time AI-powered interview helper that listens to conversations and displays prompts in big yellow text (high contrast for low vision).

### Two-Tier Architecture

**Cost optimization**: Instead of sending full CV + job description on every 2-second audio chunk, we use a lightweight sentinel model to detect when something important happens, then only fire the full-context model when needed.

**Tier 1 - Sentinel (Flash Lite, every chunk)**
- Model: `gemini-2.5-flash-lite` ($0.10/1M tokens - cheapest 2.5 model)
- Fires every 2-3 seconds on raw transcript
- Tiny prompt, NO CV data, NO job description
- Job: Detect "Has a complete question been asked?" or "Has Simon finished answering?"
- Returns: `QUESTION: [text]`, `ANSWER_DONE: [summary]`, or `WAITING`

**Tier 2 - Advisor (Flash, on-demand)**
- Model: `gemini-2.5-flash`
- Only fires when Sentinel detects a question or completed answer
- Full context: CV_FULL_TEXT, CV_SUPPLEMENTARY, job description, conversation history
- Generates actual 1-2 line hints

**Result**: ~90% cost reduction. Sentinel fires 30x per minute at ~$0.00001 each. Advisor fires maybe once per minute at ~$0.0001 each.

### Location
All interview assistant code lives in `src/services/`:
- `interview_assistant.py` - Sentinel + Advisor classes, ConversationBuffer
- `interview_display.py` - Tkinter high-contrast display window
- `interview_audio.py` - Audio capture + Faster Whisper transcription
- `interview_runner.py` - Wires everything together, provides audio/manual modes

### Running

```bash
# Interactive menu
python src/main.py          # Select option [11]

# CLI with job number (loads context from DB)
python src/main.py interview 4346719111

# CLI with URL
python src/main.py interview https://www.linkedin.com/jobs/view/4346719111/

# CLI without job context
python src/main.py interview
```

### How It Works
1. User selects audio mode (Whisper transcription) or manual mode (type what interviewer says)
2. If a job number/URL is provided, loads job data from DB for context-aware prompts
3. **Audio mode**: Whisper transcribes -> Sentinel analyzes -> Advisor responds (if needed)
4. **Manual mode**: Bypasses Sentinel, goes straight to Advisor (user already labeled who spoke)
5. Hints displayed in big yellow text on a topmost window

### Job Context
The assistant accepts an optional `job_data` dict (from DB). When provided:
- Job title, company, and description are included in Advisor's system prompt
- Without job data, runs in generic mode using only CV context

### Configuration
All interview settings are in `src/config.py` under `INTERVIEW_*` prefix:
- `INTERVIEW_SENTINEL_MODEL` - Lightweight model for real-time detection (default: gemini-2.5-flash-lite)
- `INTERVIEW_ADVISOR_MODEL` - Full-context model for hints (default: gemini-2.5-flash)
- `INTERVIEW_WHISPER_MODEL` - Whisper model size (default: base.en)
- `INTERVIEW_DISPLAY_FONT_SIZE` - Font size for big text (default: 48)
- Audio settings: sample rate, chunk duration, silence threshold

### Dependencies (Audio Mode Only)
```bash
pip install faster-whisper sounddevice
```
Manual mode has no extra dependencies beyond the base project.

### Legacy
The original `interview_assistant/` directory at project root is the predecessor. The `src/services/` version shares the main project's config, database, API keys, and CV data instead of maintaining separate copies.
