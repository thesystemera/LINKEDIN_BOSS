import sys, json, re
from pathlib import Path
from playwright.sync_api import sync_playwright

JS = Path(__file__).resolve().parent.parent.joinpath("src/services/form_engine/dom_scan.js").read_text(encoding="utf-8")

def load(page, path):
    html = Path(path).read_text(encoding="utf-8", errors="ignore")
    html = re.sub(r"^<!--.*?-->", "", html, count=1, flags=re.S)
    if "<html" not in html.lower():
        html = f'<html><body><div role="dialog" class="jobs-easy-apply-modal" style="width:800px">{html}</div></body></html>'
    page.set_content(html, wait_until="domcontentloaded")

def main(paths, verbose):
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        page = b.new_page(viewport={"width": 1280, "height": 1800})
        for path in paths:
            load(page, path)
            r = page.evaluate(JS, {})
            print(f"\n=== {Path(path).name} root={r['rootTag']} fields={len(r['fields'])} buttons={[ (x['kind'],x['text'][:25]) for x in r['buttons']]} errors={r['errors'][:3]}")
            for f in r["fields"]:
                print(f"  {f['fid']:4} {f['kind']:9} req={int(f['required'])} L='{f['label'][:70]}' Q='{f['question'][:70]}' opts={f['options'][:5]} val='{str(f['value'])[:30]}' err={f['errors'][:1]}" + (f" num={f.get('numeric')}" if f['kind']=='text' else ''))
        b.close()

if __name__ == "__main__":
    main(sys.argv[1:], True)
