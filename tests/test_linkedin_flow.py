import sys, json, re, asyncio, tempfile
from pathlib import Path
TMP = Path(tempfile.gettempdir()) / "lb_tests"
TMP.mkdir(exist_ok=True)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import nest_asyncio; nest_asyncio.apply()
from src.config import settings
settings.DB_PATH = str(TMP / "test_flow.db")
settings.MANUAL_APPROVAL = False
settings.HUMAN_TYPING = False
settings.VISION_ASSIST = False
settings.COVER_LETTER_DIR = TMP / "cover_letters"
import os
if os.path.exists(settings.DB_PATH) and __name__ == "__main__":
    os.remove(settings.DB_PATH)
import migrate_db
from src.services.database import Database
Database(settings.DB_PATH); migrate_db.apply_v2(settings.DB_PATH)
from src.services.ai_service import AIService

CALLS = []
async def fake_structured(self, prompt, schema, role="forms", temperature=None, system=None, images=None):
    CALLS.append((role, schema.__name__))
    if schema.__name__ == "CoverLetter":
        return {"letter": "Dear Hiring Team,\nI build LLM systems end to end.\nKind regards,\nSimon Che de Boer"}
    m = re.search(r"(FIELDS|QUESTIONS):\n(\[.*\])\s*$", prompt, re.S)
    items = json.loads(m.group(2)) if m else []
    out = []
    for it in items:
        q = it.get("question", "")
        if it.get("options"):
            opts = [o for o in it["options"] if not re.match(r"select an option", o, re.I)]
            a = "Yes" if "Yes" in opts else (opts[0] if opts else "")
        elif it.get("numeric") or re.search(r"how many years", q, re.I):
            a = ("ten" if __import__("os").environ.get("BADFIRST") else "10.0") if not it.get("validation_errors") else "10"
        elif schema.__name__ == "LongAnswers":
            a = "I have shipped multi-model LLM platforms (PLAiR) with FastAPI and React, which maps directly to deploying agents with customers."
        else:
            a = "Test"
        out.append({"fid": it["fid"], "answer": a, "scope": "global", "confidence": 80, "needs_human": False})
    return {"answers": out}
AIService.structured = fake_structured

from playwright.sync_api import sync_playwright
from src.services.appliers import LinkedInApplier, ExternalApplier, FormRunner

cv = TMP / "test_cv.docx"
from docx import Document
d = Document(); d.add_paragraph("Test CV - not a real application document"); d.save(str(cv))
settings.CV_FILES = {k: str(cv) for k in settings.CV_FILES}

job = {"id": 1, "linkedin_job_id": "123", "title": "Forward Deployed Engineer", "company": "Acme AI", "url": "x", "location": "Auckland, New Zealand", "description": "LLM deployment", "lane": "fde"}
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome")
    page = b.new_page(viewport={"width": 1400, "height": 1000})
    page.goto((ROOT / "tests/fixtures/li_job.html").as_uri())
    li = LinkedInApplier(FormRunner(), None)
    print("state:", li.job_state(page))
    res = li.easy_apply(page, job)
    print("RESULT:", res.status, res.error, res.steps)
    for q in res.qa:
        print(f"   [{q['source']}] {q['question'][:60]} -> {str(q['answer'])[:60]} ok={q['ok']}")
    fr = [f for f in page.frames if f != page.main_frame][0]
    print("submitted:", fr.evaluate("() => !!window.__submitted"), "followed:", fr.evaluate("() => !!window.__followed"))
    print("AI calls:", CALLS)
    b.close()
