# LinkedIn Boss 🤖

AI-powered LinkedIn Easy Apply automation bot. Scrapes jobs, evaluates fit with Gemini AI, and submits applications automatically.

Built with Playwright + Google Gemini. Targets 200+ applications over 30 days.

> **Note:** This violates LinkedIn's Terms of Service. Use at your own risk. Rate limiting and human-like behaviour are built in to reduce ban risk.

---

## Features

- **Multi-location job search** — searches multiple locations, deduplicates across all
- **AI job evaluation** — Gemini scores each job against your CV before applying
- **Two-stage form filling** — Flash model for simple fields, Pro model for cover letters only (cost optimised)
- **Manual approval mode** — review each application before it submits
- **Dry run mode** — see what would happen without submitting anything
- **Validation retry** — automatically fixes form validation errors (e.g. "enter a whole number")
- **Interview assistant** — real-time AI hints during interviews via audio transcription
- **Debug HTML capture** — saves LinkedIn modal HTML when forms fail, for selector debugging

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Get a Gemini API key

Get one free at [Google AI Studio](https://aistudio.google.com/app/apikey), then:

```bash
mkdir -p src/keys
echo "YOUR_API_KEY_HERE" > src/keys/gemini_key.txt
```

### 3. Set up your CV data

```bash
cp src/services/cv_data_example.py src/services/cv_data.py
```

Edit `src/services/cv_data.py` with your own details — this is the single source of truth the AI uses for all form filling, evaluation, and cover letters.

### 4. Configure your search

Edit `src/config.py`:

```python
SEARCH_KEYWORDS = ["software engineer", "your job title"]
SEARCH_LOCATIONS = ["Your City", "Your Country"]
```

### 5. Login to LinkedIn

```bash
python src/main.py setup
```

A browser window will open. Log in manually. Your session is saved for future runs.

---

## Usage

```bash
# Interactive menu (recommended)
python src/main.py

# Direct commands
python src/main.py run      # Run the full pipeline
python src/main.py stats    # View statistics
python src/main.py review   # Jobs needing manual review
python src/main.py reset    # Clear the database
```

### Interactive menu options

```
[1] Run automation (with manual approval)
[2] Run automation (auto mode)
[3] Dry run (show what would happen, don't submit)
[4] Setup (login to LinkedIn)
[5] View statistics
[6] Review jobs needing manual attention
[7] Reset database
[11] Interview assistant
```

---

## Architecture

```
Job Scraping → AI Evaluation → Application Submission
```

1. **Scraper** — searches LinkedIn for Easy Apply jobs across configured locations
2. **Evaluator** — Gemini scores each job against your CV (Flash model, cheap)
3. **Applier** — fills forms using two-stage AI (Flash for fields, Pro for cover letters only)

### Cost optimisation

All form fields are sent to Gemini in **one batch call**, not per field. Two-stage triage means the expensive Pro model is only called when there's a cover letter or complex essay. Typical cost: ~$0.02/month.

### Database

SQLite at `data/applications.db`. Four tables: `jobs`, `evaluations`, `applications`, `daily_stats`.

---

## Configuration

Key settings in `src/config.py`:

| Setting | Default | Description |
|---|---|---|
| `MAX_APPLICATIONS_PER_DAY` | 100 | Hard daily limit |
| `HEADLESS` | False | Keep False — visible browser looks human |
| `MANUAL_APPROVAL` | True | Prompt before each submission |
| `DRY_RUN` | False | Stop before clicking Submit |
| `ENABLE_VALIDATION_RETRY` | True | Auto-fix form validation errors |
| `SEARCH_KEYWORDS` | [...] | Job titles to search for |
| `SEARCH_LOCATIONS` | [...] | Locations to search in |

---

## Interview Assistant

Real-time AI hints during interviews. Listens via microphone (Whisper transcription) or manual text input, displays suggestions in large high-contrast text.

```bash
# With job context from DB
python src/main.py interview 4346719111

# Generic mode
python src/main.py interview
```

Extra dependencies for audio mode:
```bash
pip install faster-whisper sounddevice
```

---

## File Structure

```
src/
├── main.py                  # Entry point + CLI
├── config.py                # All configuration
└── services/
    ├── cv_data.py           # YOUR CV data (gitignored - you create this)
    ├── cv_data_example.py   # Template to copy from
    ├── job_scraper.py       # LinkedIn scraping
    ├── job_evaluator.py     # Gemini AI evaluation
    ├── auto_applier.py      # Application submission
    ├── form_field_filler.py # Form field detection + AI filling
    ├── database.py          # SQLite operations
    ├── session_manager.py   # LinkedIn session persistence
    ├── interview_assistant.py
    ├── interview_audio.py
    ├── interview_display.py
    └── interview_runner.py

data/                        # Gitignored - created on first run
├── applications.db
├── linkedin_session.json
└── debug_html/

src/keys/                    # Gitignored - you create this
└── gemini_key.txt
```

---

## Troubleshooting

**Scraper finds 0 jobs** — LinkedIn changes HTML structure periodically. Check logs for `[WARNING] Card X: Missing elements`. Save a LinkedIn page to `src/page_structure/` and update selectors in `job_scraper.py`.

**Session expired** — Run `python src/main.py setup` again.

**Form validation errors** — Automatic retry is built in. If still failing, check `data/debug_html/` for captured modal HTML.

**asyncio warnings** — `RuntimeError: Leaving task does not match current task` from nest_asyncio is safe to ignore.

---

## Database Migrations

```bash
python migrate_db.py
# [1] Add description column
# [2] Clean duplicate URLs
```

---

## Gemini Models Used

| Purpose | Model |
|---|---|
| Job evaluation | gemini-2.5-flash |
| Form field triage | gemini-2.5-flash |
| Cover letters | gemini-2.5-pro |
| Interview sentinel | gemini-2.5-flash-lite |
| Interview advisor | gemini-2.5-flash |

---

## License

MIT — do whatever you want with it.
