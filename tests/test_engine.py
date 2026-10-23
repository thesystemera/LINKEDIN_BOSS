import sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from playwright.sync_api import sync_playwright
from src.services.form_engine.engine import FormEngine

ANSWERS = {
    "First Name": "Simon", "Last Name": "Che de Boer", "Email": "simon@example.com", "Phone": "+64211490191",
    "How many years of Python": "10", "Country": "New Zealand", "legally authorized": "Yes",
    "Languages": "English; Māori", "visa sponsorship": "No", "Current location": "Auckland, New Zealand",
    "How did you hear": "LinkedIn", "Expected salary": "165000", "Why do you want": "Because the work is a direct fit.",
    "Resume": str(ROOT / "tests/fixtures/dummy_cv.docx"), "I confirm": "Yes",
}

def main():
    (ROOT / "tests/fixtures/dummy_cv.docx").write_bytes(b"PK dummy")
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        page = b.new_page(viewport={"width": 1280, "height": 2000})
        page.goto((ROOT / "tests/fixtures/synthetic_form.html").as_uri())
        eng = FormEngine(page, human_typing=False)
        snap = eng.scan()
        fails = 0
        for f in snap.fields:
            ans = next((v for k, v in ANSWERS.items() if k.lower() in f.text.lower()), None)
            if f.kind == "combobox":
                print("   probe:", eng.probe_options(f)[:5])
            ok, got = eng.fill(f, ans) if ans is not None else (False, "NO ANSWER")
            fails += 0 if ok else 1
            print(f"{'OK ' if ok else 'FAIL'} {f.kind:9} {f.text[:55]:55} -> {str(got)[:50]}")
        snap2 = eng.scan()
        for f in snap2.fields:
            print(f"   after: {f.kind:9} {f.text[:40]:40} value='{str(f.value)[:40]}'")
        btn = snap2.button("submit")
        print("submit button:", btn.text if btn else None)
        eng.click(btn, wait=0.5)
        print("success:", eng.scan().success, "fails:", fails)
        b.close()

main()
