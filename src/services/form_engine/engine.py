import re
import time
import random
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from playwright.sync_api import Page, Frame, Locator

from src.services.form_engine.matching import match_option, split_multi, truthy, norm
from src.utils.logger import custom_print

SCAN_JS = (Path(__file__).parent / "dom_scan.js").read_text(encoding="utf-8")

OPTIONS_JS = """
(args) => {
  const [fid, maxN] = args;
  const clean = s => (s || '').replace(/\\s+/g, ' ').trim();
  const vis = e => { const r = e.getBoundingClientRect(); const cs = getComputedStyle(e); return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none'; };
  document.querySelectorAll('[data-lb-o]').forEach(e => e.removeAttribute('data-lb-o'));
  const el = document.querySelector(`[data-lb-fid="${fid}"]`);
  if (!el) return [];
  let boxes = [];
  for (const a of ['aria-controls', 'aria-owns']) {
    const id = el.getAttribute(a);
    if (id) { const b = document.getElementById(id); if (b && vis(b)) boxes.push(b); }
  }
  if (!boxes.length) {
    const er = el.getBoundingClientRect();
    const cands = [...document.querySelectorAll('[role="listbox"], [class*="menu-list"], [class*="MenuList"], .basic-typeahead__triggered-content, [data-automation-id="activeListContainer"], ul[class*="suggest"], ul[class*="autocomplete"], .pac-container, [class*="dropdown-results"], [class*="dropdown-container"] ul')].filter(vis);
    cands.sort((a, b) => {
      const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
      return (Math.abs(ra.top - er.bottom) + Math.abs(ra.left - er.left)) - (Math.abs(rb.top - er.bottom) + Math.abs(rb.left - er.left));
    });
    boxes = cands.slice(0, 1);
  }
  const out = [];
  let k = 0;
  for (const b of boxes) {
    let opts = [...b.querySelectorAll('[role="option"], [class*="option"]:not([class*="options"]), li, .pac-item, [class*="dropdown-location"]')].filter(vis);
    opts = opts.filter(o => !opts.some(p => p !== o && o.contains(p)));
    for (const o of opts) {
      const t = clean(o.innerText);
      if (!t || /^(no (results|options|matches)|loading|searching)/i.test(t)) continue;
      o.setAttribute('data-lb-o', String(k));
      out.push(t);
      k++;
      if (k >= maxN) return out;
    }
  }
  return out;
}
"""

RETAG_JS = """
([fid, name, id, expected]) => {
  let els = name ? [...document.querySelectorAll(`input[name="${CSS.escape(name)}"], select[name="${CSS.escape(name)}"], textarea[name="${CSS.escape(name)}"]`)] : [];
  if (!els.length && expected) {
    const g = document.querySelector(`[data-lb-grp="${fid}"]`);
    if (g) els = [...g.querySelectorAll('input[type="checkbox"], input[type="radio"]')];
  }
  if (!els.length && id) { const e = document.getElementById(id); if (e) els = [e]; }
  if (expected && els.length !== expected) return 0;
  els.forEach((e, i) => {
    e.setAttribute('data-lb-fid', fid);
    if (e.type === 'radio' || e.type === 'checkbox') e.setAttribute('data-lb-opt', String(i));
  });
  return els.length;
}
"""

READ_VALUE_JS = """
(el) => {
  const clean = s => (s || '').replace(/\\s+/g, ' ').trim();
  const fid = el.getAttribute('data-lb-fid');
  const all = [...document.querySelectorAll(`[data-lb-fid="${fid}"]`)];
  const tag = el.tagName.toLowerCase();
  const type = (el.getAttribute('type') || '').toLowerCase();
  if (type === 'radio' || type === 'checkbox' || el.getAttribute('role') === 'radio' || el.getAttribute('role') === 'checkbox' || el.hasAttribute('aria-pressed')) {
    return all.filter(m => m.tagName === 'INPUT' ? m.checked : (m.getAttribute('aria-checked') === 'true' || m.getAttribute('aria-pressed') === 'true')).map(m => m.getAttribute('data-lb-opt')).join(',');
  }
  if (tag === 'select') { const o = el.options[el.selectedIndex]; return o ? clean(o.text) : ''; }
  if (type === 'file') {
    if (el.files && el.files.length) return el.files[0].name;
    let p = el.parentElement; for (let i = 0; i < 4 && p; i++) { const m = (p.innerText || '').match(/(?:^|\\s)([\\w\\-()]+(?:\\.[\\w\\-()]+)*\\.(pdf|docx?|txt|rtf|odt))(?=\\s|$)/i); if (m) return m[1]; p = p.parentElement; }
    return '';
  }
  if (tag === 'button') return clean(el.innerText);
  if (el.getAttribute('contenteditable') === 'true') return clean(el.innerText);
  const v = clean(el.value);
  if (v) return v;
  let p = el.parentElement;
  for (let i = 0; i < 5 && p; i++) {
    const sv = p.querySelector('[class*="single-value"], [class*="singleValue"], [data-automation-id="selectedItem"], [class*="multi-value__label"]');
    if (sv) return clean(sv.innerText);
    p = p.parentElement;
  }
  return '';
}
"""


@dataclass
class Field:
    raw: Dict[str, Any]
    frame: Frame

    def __getattr__(self, item):
        raw = self.__dict__.get("raw", {})
        if item in raw:
            return raw[item]
        raise AttributeError(item)

    @property
    def text(self) -> str:
        q, l = (self.raw.get("question") or "").strip(), (self.raw.get("label") or "").strip()
        if self.raw.get("kind") == "file" and q and l and q != l:
            return f"{l} ({q})"
        if q and l and q != l and l not in q:
            return f"{q} — {l}"
        return q or l or self.raw.get("placeholder") or self.raw.get("name") or ""

    @property
    def filled(self) -> bool:
        v = self.raw.get("value")
        return bool(v and str(v).strip())

    def summary(self) -> Dict[str, Any]:
        d = {"fid": self.fid, "kind": self.kind, "question": self.text[:400], "required": self.required}
        ph = self.raw.get("placeholderOption")
        if self.raw.get("options"):
            d["options"] = [o for o in self.raw["options"] if o != ph][:150]
        for k in ("section", "placeholder", "maxlength", "numeric", "decimal", "min", "max", "multiple", "value", "errors", "autocomplete", "inputType"):
            v = self.raw.get(k)
            if v not in (None, "", [], False):
                d[k] = v[:150] if k == "options" and isinstance(v, list) else v
        return d


@dataclass
class Button:
    raw: Dict[str, Any]
    frame: Frame

    @property
    def kind(self):
        return self.raw["kind"]

    @property
    def text(self):
        return self.raw["text"]

    @property
    def disabled(self):
        return self.raw["disabled"]


@dataclass
class Snapshot:
    fields: List[Field] = dc_field(default_factory=list)
    buttons: List[Button] = dc_field(default_factory=list)
    errors: List[str] = dc_field(default_factory=list)
    success: bool = False
    captcha: bool = False
    url: str = ""
    headings: List[str] = dc_field(default_factory=list)
    progress: Optional[str] = None
    root_text: str = ""

    def signature(self) -> str:
        f = "|".join(sorted(f"{x.kind}:{x.text[:60]}" for x in self.fields))
        b = "|".join(sorted(f"{x.kind}:{x.text[:30]}" for x in self.buttons if x.kind in ("next", "review", "submit")))
        return f"{self.progress}#{f}#{b}"

    def field_errors(self) -> List[Tuple[Field, List[str]]]:
        return [(f, f.errors) for f in self.fields if f.errors or f.invalid]

    def all_errors(self) -> List[str]:
        out = list(self.errors)
        for f, errs in self.field_errors():
            for e in errs or ["invalid value"]:
                s = f"{f.text[:80]}: {e}"
                if s not in out:
                    out.append(s)
        return out

    def button(self, *kinds) -> Optional[Button]:
        for k in kinds:
            cands = [b for b in self.buttons if b.kind == k and not b.disabled]
            if not cands:
                continue
            if k == "submit":
                typed = [b for b in cands if b.raw.get("type") == "submit"]
                return (typed or cands)[-1]
            return cands[0]
        return None


class FormEngine:
    def __init__(self, page: Page, root_selector: Optional[str] = None, human_typing: bool = True, strict_root: bool = False):
        self.page = page
        self.root_selector = root_selector
        self.human_typing = human_typing
        self.strict_root = strict_root

    SKIP_FRAME_HOSTS = re.compile(r"(^|\.)(doubleclick\.net|googletagmanager\.com|google-analytics\.com|googlesyndication\.com|facebook\.(com|net)|recaptcha\.net|hcaptcha\.com|challenges\.cloudflare\.com|hotjar\.com|bat\.bing\.com|ads\.linkedin\.com|px\.ads\.linkedin\.com)$", re.I)

    def frames(self) -> List[Frame]:
        from urllib.parse import urlparse
        out = [self.page.main_frame]
        for fr in self.page.frames:
            if fr is self.page.main_frame:
                continue
            u = fr.url or ""
            if not u or u == "about:blank":
                continue
            pu = urlparse(u)
            host = pu.hostname or ""
            if self.SKIP_FRAME_HOSTS.search(host) or (host.endswith("google.com") and "/recaptcha" in pu.path) or "/li/track" in pu.path:
                continue
            out.append(fr)
        return out

    def scan(self) -> Snapshot:
        snap = Snapshot(url=self.page.url)
        for idx, fr in enumerate(self.frames()):
            try:
                r = fr.evaluate(SCAN_JS, {"prefix": f"x{idx}f", "rootSelector": self.root_selector, "strictRoot": self.strict_root})
            except Exception as e:
                if idx == 0:
                    custom_print("WARNING", f"Form scan failed in main frame: {str(e)[:120]}")
                continue
            if r.get("rootTag") == "none":
                continue
            if idx > 0 and r.get("rootTag") == "body" and not r["fields"] and not r["success"]:
                continue
            snap.fields.extend(Field(f, fr) for f in r["fields"])
            snap.buttons.extend(Button({**b, "bid": b["bid"]}, fr) for b in r["buttons"])
            snap.errors.extend(e for e in r["errors"] if e not in snap.errors)
            snap.success = snap.success or r["success"]
            snap.captcha = snap.captcha or r["captcha"]
            if idx == 0 or (not snap.headings and r["headings"]):
                snap.headings = r["headings"] or snap.headings
                snap.progress = r["progress"] or snap.progress
                snap.root_text = r["rootText"] or snap.root_text
        return snap

    def loc(self, f: Field) -> Locator:
        return f.frame.locator(f'[data-lb-fid="{f.fid}"]').first

    def present(self, f: Field) -> bool:
        """True if the field is still on the page. React forms (LinkedIn) re-render inputs after a click, which drops
        our data-lb-* tags: re-tag by the input's name (stable across re-renders) or id."""
        try:
            name = f.raw.get("name") or ""
            # option groups are re-tagged every time: React may replace only the clicked option
            if f.kind in ("radio", "checkbox") and len(f.options or []) > 1 and f.frame.evaluate(RETAG_JS, [f.fid, name, "", len(f.options)]):
                return True
            if self.loc(f).count():
                return True
            return bool(f.frame.evaluate(RETAG_JS, [f.fid, name, f.raw.get("elId") or "", 0]))
        except Exception:
            return False

    def opt_loc(self, f: Field, i: int) -> Locator:
        return f.frame.locator(f'[data-lb-fid="{f.fid}"][data-lb-opt="{i}"]').first

    def btn_loc(self, b: Button) -> Locator:
        return b.frame.locator(f'[data-lb-bid="{b.raw["bid"]}"]').first

    def _pause(self, lo=0.15, hi=0.45):
        time.sleep(random.uniform(lo, hi))

    def read_value(self, f: Field) -> str:
        try:
            if not self.present(f):
                return ""
            return self.loc(f).evaluate(READ_VALUE_JS, timeout=3000) or ""
        except Exception:
            return ""

    def visible_options(self, f: Field, max_n: int = 300) -> List[str]:
        try:
            return f.frame.evaluate(OPTIONS_JS, [f.fid, max_n])
        except Exception:
            return []

    def click_option(self, f: Field, k: int) -> bool:
        o = f.frame.locator(f'[data-lb-o="{k}"]').first
        try:
            o.scroll_into_view_if_needed(timeout=2000)
            o.click(timeout=3000)
            return True
        except Exception:
            try:
                o.evaluate("e => { e.dispatchEvent(new MouseEvent('mousedown', {bubbles:true})); e.click(); }")
                return True
            except Exception:
                return False

    def probe_options(self, f: Field) -> List[str]:
        if f.kind != "combobox" or f.options:
            return f.options or []
        l = self.loc(f)
        opts: List[str] = []
        try:
            l.scroll_into_view_if_needed(timeout=2000)
            l.click(timeout=3000)
            time.sleep(0.6)
            opts = self.visible_options(f)
            if not opts and f.comboVariant == "input":
                l.press("ArrowDown")
                time.sleep(0.5)
                opts = self.visible_options(f)
        except Exception:
            pass
        finally:
            try:
                l.press("Escape")
            except Exception:
                pass
            time.sleep(0.2)
            if f.comboVariant == "button" and self.visible_options(f, 3):
                try:
                    l.click(timeout=2000)
                except Exception:
                    pass
        f.raw["options"] = opts
        f.raw["options_probed"] = True
        return opts

    def _dispatch(self, l: Locator):
        try:
            l.evaluate("""e => { e.dispatchEvent(new Event('input', {bubbles:true})); e.dispatchEvent(new Event('change', {bubbles:true})); e.dispatchEvent(new Event('blur', {bubbles:true})); }""")
        except Exception:
            pass

    def _type_text(self, l: Locator, value: str, short_limit: int = 80):
        l.scroll_into_view_if_needed(timeout=3000)
        try:
            l.click(timeout=3000)
        except Exception:
            l.focus()
        l.fill("")
        if self.human_typing and len(value) <= short_limit:
            l.press_sequentially(value, delay=random.randint(25, 70))
        else:
            l.fill(value)

    def _maybe_pick_suggestion(self, f: Field, value: str) -> bool:
        time.sleep(0.9)
        opts = self.visible_options(f, 30)
        if not opts:
            return False
        i = match_option(value, opts, fuzzy_cutoff=0.45)
        if i is None and re.search(r"location|city|address|suburb|town", f.text, re.I):
            i = 0
        if i is None:
            return False
        return self.click_option(f, i)

    def fill(self, f: Field, answer: Any) -> Tuple[bool, str]:
        try:
            kind = f.kind
            if kind in ("text", "date"):
                return self._fill_text(f, answer)
            if kind == "textarea":
                return self._fill_textarea(f, answer)
            if kind == "select":
                return self._fill_select(f, answer)
            if kind in ("radio", "toggle"):
                return self._fill_choice(f, answer)
            if kind == "checkbox":
                return self._fill_checkbox(f, answer)
            if kind == "combobox":
                return self._fill_combobox(f, answer)
            if kind == "file":
                return self._fill_file(f, answer)
            return False, f"unsupported kind {kind}"
        except Exception as e:
            return False, str(e)[:160]

    def _fill_text(self, f: Field, answer: Any) -> Tuple[bool, str]:
        value = "" if answer is None else str(answer).strip()
        if f.kind == "date" and f.inputType == "date":
            m = re.search(r"(\d{4})-(\d{2})-(\d{2})", value)
            value = m.group(0) if m else value
        if f.raw.get("numeric"):
            num = re.sub(r"[^\d.\-]", "", value.replace(",", ""))
            if num and not f.raw.get("decimal") and re.search(r"year|month|week|day|how many|number of", f.text, re.I):
                try:
                    num = str(int(round(float(num))))
                except ValueError:
                    pass
            elif num and f.raw.get("decimal") and "." not in num:
                num = f"{num}.0"
            value = num or value
        ml = f.raw.get("maxlength")
        if isinstance(ml, int) and ml > 0 and len(value) > ml:
            value = value[:ml]
        l = self.loc(f)
        self._type_text(l, value)
        self._dispatch(l)
        self._maybe_pick_suggestion(f, value)
        self._pause()
        got = self.read_value(f)
        if not got and value:
            l.fill(value)
            self._dispatch(l)
            got = self.read_value(f)
        return (bool(got) or not value), got

    def _fill_textarea(self, f: Field, answer: Any) -> Tuple[bool, str]:
        value = "" if answer is None else str(answer).strip()
        ml = f.raw.get("maxlength")
        if isinstance(ml, int) and ml > 0 and len(value) > ml:
            cut = value[:ml]
            value = cut[: cut.rfind(". ") + 1] if ". " in cut else cut
        l = self.loc(f)
        l.scroll_into_view_if_needed(timeout=3000)
        if f.tag != "textarea":
            l.click()
            self.page.keyboard.press("Control+A")
            self.page.keyboard.insert_text(value)
        else:
            l.fill(value)
        self._dispatch(l)
        self._pause()
        got = self.read_value(f)
        return (bool(got) or not value), f"{len(got)} chars"

    def _fill_select(self, f: Field, answer: Any) -> Tuple[bool, str]:
        options = [o for o in f.options if o != f.raw.get("placeholderOption")]
        answers = split_multi(answer) if f.raw.get("multiple") else [answer]
        l = self.loc(f)
        chosen = []
        for a in answers:
            i = match_option(a, options)
            if i is None:
                continue
            chosen.append(options[i])
        if not chosen:
            return False, f"no option matches '{str(answer)[:60]}'"
        l.scroll_into_view_if_needed(timeout=3000)
        idxs = l.evaluate("(el, ts) => { const c = s => (s||'').replace(/\\s+/g,' ').trim(); return ts.map(t => [...el.options].findIndex(o => c(o.text) === t)).filter(i => i >= 0); }", chosen)
        if not idxs:
            return False, "option index not found"
        if f.raw.get("multiple"):
            l.select_option(index=idxs)
        else:
            l.select_option(index=idxs[0])
        self._dispatch(l)
        self._pause(0.3, 0.7)
        got = self.read_value(f)
        return (bool(got) and norm(got) == norm(chosen[0])), got

    def _click_member(self, f: Field, i: int) -> None:
        self.present(f)
        ol = self.opt_loc(f, i)
        try:
            ol.scroll_into_view_if_needed(timeout=2000)
        except Exception:
            pass
        try:
            ol.click(timeout=2500)
            return
        except Exception:
            pass
        el_id = ol.get_attribute("id")
        if el_id:
            lab = f.frame.locator(f'label[for="{el_id}"]').first
            try:
                lab.click(timeout=2500)
                return
            except Exception:
                pass
        ol.evaluate("e => { e.click(); e.dispatchEvent(new Event('change', {bubbles:true})); e.dispatchEvent(new Event('input', {bubbles:true})); }")

    def _fill_choice(self, f: Field, answer: Any) -> Tuple[bool, str]:
        i = match_option(answer, f.options)
        if i is None:
            return False, f"no option matches '{str(answer)[:60]}' in {f.options[:6]}"
        self._click_member(f, i)
        self._pause(0.3, 0.6)
        got = self.read_value(f)
        ok = str(i) in got.split(",")
        if not ok and self.present(f):
            self.opt_loc(f, i).evaluate("e => { if (e.tagName === 'INPUT') { e.checked = true; } e.click(); e.dispatchEvent(new Event('change', {bubbles:true})); }", timeout=3000)
            self._pause(0.3, 0.5)
            got = self.read_value(f)
            ok = str(i) in got.split(",")
        return ok, f.options[i]

    def _fill_checkbox(self, f: Field, answer: Any) -> Tuple[bool, str]:
        if f.raw.get("single") or len(f.options) == 1:
            want = truthy(answer)
            if want is None:
                want = bool(answer) and match_option(answer, f.options) is not None
            got = self.read_value(f)
            is_on = got.strip() != ""
            if want != is_on:
                self._click_member(f, 0)
                self._pause(0.3, 0.6)
                is_on = self.read_value(f).strip() != ""
            return is_on == want, "checked" if is_on else "unchecked"
        wanted = set()
        for a in split_multi(answer):
            i = match_option(a, f.options)
            if i is not None:
                wanted.add(i)
        if not wanted:
            return False, f"no options match '{str(answer)[:60]}'"
        current = {int(x) for x in self.read_value(f).split(",") if x.strip().isdigit()}
        for i in sorted(wanted - current):
            self._click_member(f, i)
            self._pause(0.2, 0.4)
        after = {int(x) for x in self.read_value(f).split(",") if x.strip().isdigit()}
        return wanted.issubset(after), "; ".join(f.options[i] for i in sorted(wanted))

    def _fill_combobox(self, f: Field, answer: Any) -> Tuple[bool, str]:
        answers = split_multi(answer) if f.raw.get("multiple") else [str(answer)]
        picked = []
        l = self.loc(f)
        for a in answers:
            if not a:
                continue
            done = False
            opts = self._open_combo(f, l)
            i = match_option(a, opts) if opts else None
            if i is not None:
                done = self.click_option(f, i)
                if done:
                    picked.append(opts[i])
            if not done and f.comboVariant == "input":
                for term in self._search_terms(a):
                    l.fill("")
                    l.press_sequentially(term, delay=random.randint(30, 70))
                    time.sleep(1.2)
                    opts = self.visible_options(f)
                    if not opts:
                        continue
                    i = match_option(a, opts, fuzzy_cutoff=0.5)
                    if i is None and len(opts) == 1:
                        i = 0
                    if i is None and re.search(r"location|city|country|address", f.text, re.I):
                        i = 0
                    if i is not None and self.click_option(f, i):
                        picked.append(opts[i])
                        done = True
                        break
                if not done:
                    try:
                        l.press("Escape")
                    except Exception:
                        pass
            elif not done:
                popup_search = f.frame.locator('[data-automation-id="searchBox"] input, [role="dialog"] input[type="search"], [data-automation-id="multiselectInputContainer"] input').first
                if popup_search.count():
                    popup_search.fill(a[:40])
                    popup_search.press("Enter")
                    time.sleep(1.2)
                    opts = self.visible_options(f)
                    i = match_option(a, opts, fuzzy_cutoff=0.5)
                    if i is not None and self.click_option(f, i):
                        picked.append(opts[i])
                        done = True
                if not done:
                    try:
                        self.page.keyboard.press("Escape")
                    except Exception:
                        pass
            self._pause(0.3, 0.6)
        got = self.read_value(f)
        return bool(picked) and bool(got), got or "; ".join(picked)

    def _open_combo(self, f: Field, l: Locator) -> List[str]:
        opts = self.visible_options(f)
        if opts:
            return opts
        l.scroll_into_view_if_needed(timeout=3000)
        for _ in range(2):
            try:
                l.click(timeout=3000)
            except Exception:
                l.evaluate("e => e.click()")
            time.sleep(0.6)
            opts = self.visible_options(f)
            if opts:
                return opts
        return []

    def _search_terms(self, a: str) -> List[str]:
        a = a.strip()
        terms = []
        first = re.split(r"[,(/\-–]", a)[0].strip()
        if first and first != a:
            terms.append(first[:40])
        terms.append(a[:40])
        words = a.split()
        if len(words) > 2:
            terms.append(" ".join(words[:2]))
        seen, out = set(), []
        for t in terms:
            if t and t.lower() not in seen:
                seen.add(t.lower())
                out.append(t)
        return out

    def _fill_file(self, f: Field, answer: Any) -> Tuple[bool, str]:
        path = Path(str(answer))
        if not path.exists():
            return False, f"file not found: {path}"
        l = self.loc(f)
        l.set_input_files(str(path))
        time.sleep(2.0)
        got = self.read_value(f)
        return True, got or path.name

    def click(self, b: Button, wait: float = 2.0) -> bool:
        l = self.btn_loc(b)
        try:
            l.scroll_into_view_if_needed(timeout=3000)
            self._pause(0.3, 0.8)
            l.click(timeout=5000)
        except Exception:
            try:
                l.evaluate("e => e.click()")
            except Exception as e:
                custom_print("WARNING", f"Could not click '{b.text}': {str(e)[:100]}")
                return False
        time.sleep(wait + random.uniform(0, 0.8))
        return True

    def click_text(self, pattern: str, roles=("button", "link"), timeout: int = 3000) -> bool:
        rx = re.compile(pattern, re.I)
        for role in roles:
            l = self.page.get_by_role(role, name=rx)
            try:
                n = l.count()
            except Exception:
                n = 0
            for i in range(n):
                el = l.nth(i)
                try:
                    if el.is_visible():
                        el.click(timeout=timeout)
                        return True
                except Exception:
                    continue
        return False
