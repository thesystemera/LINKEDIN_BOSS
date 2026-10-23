import sys, re
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import test_linkedin_flow as base
from src.config import settings
settings.EXTERNAL_AUTO_SUBMIT["generic"] = True
settings.EXTERNAL_READ_TIME_MIN = settings.EXTERNAL_READ_TIME_MAX = 0
from playwright.sync_api import sync_playwright
from src.services.appliers import ExternalApplier, FormRunner
job = {"id": 2, "linkedin_job_id": "456", "title": "Forward Deployed Engineer", "company": "Synth", "url": "x", "location": "Remote - New Zealand", "description": "LLM deployment", "lane": "fde"}
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome")
    for run in (1, 2):
        base.CALLS.clear()
        page = b.new_page(viewport={"width": 1400, "height": 1800})
        res = ExternalApplier(FormRunner()).apply(page, job, url=(ROOT / "tests/fixtures/synthetic_form.html").as_uri())
        print(f"RUN {run}:", res.status, res.error, res.channel)
        for q in res.qa:
            print(f"   [{q['source']}] {q['question'][:55]} -> {str(q['answer'])[:50]} ok={q['ok']}")
        print("   AI calls:", base.CALLS)
        page.close()
    b.close()
