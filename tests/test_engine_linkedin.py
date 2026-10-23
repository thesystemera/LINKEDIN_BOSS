import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from playwright.sync_api import sync_playwright
from src.services.form_engine.engine import FormEngine
from scan_fixture import load

def main(paths):
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        page = b.new_page(viewport={"width": 1280, "height": 2400})
        for path in paths:
            load(page, path)
            eng = FormEngine(page, root_selector='[role="dialog"]', human_typing=False)
            snap = eng.scan()
            ok_n = 0
            for f in snap.fields:
                if f.kind == "file":
                    continue
                if f.kind in ("select", "radio", "checkbox", "toggle"):
                    opts = [o for o in f.options if o != f.raw.get("placeholderOption")]
                    ans = opts[min(1, len(opts) - 1)] if opts else "Yes"
                elif f.raw.get("numeric"):
                    ans = "5"
                else:
                    ans = "Test answer"
                ok, got = eng.fill(f, ans)
                ok_n += ok
                if not ok:
                    print(f"  FAIL {f.kind} {f.text[:60]} ans={ans!r} got={got!r}")
            print(f"{Path(path).name}: {ok_n}/{len([f for f in snap.fields if f.kind!='file'])} filled")
        b.close()

main(sys.argv[1:])
