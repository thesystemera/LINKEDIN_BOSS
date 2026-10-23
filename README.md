# LinkedIn Boss v2

Job application bot: scrapes LinkedIn (Easy Apply **and** external postings), evaluates each job with Gemini, and fills/submits applications on LinkedIn Easy Apply and on company application systems (Greenhouse, Lever, Ashby, Workday, SmartRecruiters, Workable, JobAdder, SEEK and unknown sites).

> Automating LinkedIn breaches its Terms of Service and can get the account restricted. Pacing and a real browser profile reduce, not remove, that risk.

## What changed from v1

| Area | v1 | v2 |
|---|---|---|
| Easy Apply | Waited for `[role=dialog]` in the main page; failed on ~35% of jobs once LinkedIn moved the apply flow into an iframe | Generic form engine scans every frame, finds fields by label/role, not CSS classes |
| Coverage | Easy Apply only | External applications followed into the company's application system |
| Answers | One Gemini call per page, no memory | Profile facts → saved answers (answer bank) → AI; AI answers saved only after a successful submit; you can approve/edit/reject them |
| Uploads | Bailed on any file field | Uploads the CV for the role type; writes and uploads a tailored cover letter |
| Validation | One retry on LinkedIn only | AI fix + retry on any system; failed answers are dropped from the bank |
| Stuck pages | Gave up | Vision assist (screenshot + Gemini picks the next button) |
| Queue | Ordered by AI confidence | Ordered by stated/estimated pay (NZD), stale listings dropped, reposts skipped |
| Browser | Fresh Chromium + cookie file | Persistent profile in real Chrome (keeps LinkedIn, SEEK, Workday logins) |
| Search | 40 keywords × 3 locations every run | Keyword lanes × locations (NZ, Sydney, Melbourne, AU remote, worldwide remote), rotated across runs; contract + permanent |

## Setup

```bash
pip install -U -r requirements.txt
playwright install chromium        # only needed if Google Chrome isn't installed
cp .env.example .env               # add GEMINI_API_KEY (and optionally ATS_ACCOUNT_EMAIL/PASSWORD)
python src/main.py doctor          # checks key, picks Gemini models, CV files, browser
python src/main.py setup           # log in to LinkedIn in the bot's browser profile
```

Your profile data lives in `src/services/cv_data.py` (`CV_SUPPLEMENTARY`, `CV_FULL_TEXT`, `APPLICATION_PROFILE`).
CV files per role type are set in `CV_FILES` in `src/config.py`.

## Usage

```bash
python src/main.py                 # menu
python src/main.py run             # full pipeline, manual approval
python src/main.py run --dry-run   # fill everything, never submit
python src/main.py apply <url>     # one job: LinkedIn URL/number or any application page
python src/main.py answers         # review saved answers
python src/main.py external        # work through external applications that need you
python src/main.py capture         # save page HTML/screenshots when something breaks
python src/main.py stats
```

## Architecture

```
src/services/
  browser.py              persistent Chrome profile, login checks
  job_scraper.py          LinkedIn search (lanes × locations, rotation, repost-safe)
  job_evaluator.py        description + apply type extraction, eligibility, lane, pay estimate
  form_engine/
    dom_scan.js           field/button/error scanner (labels, groups, comboboxes, files, shadow DOM)
    engine.py             fills fields with real interactions, reads values back
    matching.py           option matching (exact, yes/no, ranges, fuzzy)
    answerer.py           profile rules → answer bank → Gemini (short + long-form), cover letters
  appliers/
    base.py               step loop: scan → answer → fill → next/review/submit → validate → fix
    linkedin.py           Easy Apply (iframe-aware) + following external Apply buttons
    external.py           application-system detection and per-system preparation (login, apply buttons)
  answer_bank.py          saved answers (approved / unreviewed / rejected)
  documents.py            CV selection, CV text, cover letter .docx
```

Database migrations run automatically at startup (`migrate_db.apply_v2`).
