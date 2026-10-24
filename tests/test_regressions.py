import sys, re, json, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import nest_asyncio; nest_asyncio.apply()
from src.config import settings
TMP = Path(tempfile.gettempdir()) / "lb_reg"; TMP.mkdir(exist_ok=True)
settings.DB_PATH = str(TMP / "reg.db")
settings.HUMAN_TYPING = False
settings.COVER_LETTER_DIR = TMP / "cl"
from docx import Document
cv = TMP / "cv.docx"; d = Document(); d.add_paragraph("test cv"); d.save(str(cv))
settings.CV_FILES = {k: str(cv) for k in settings.CV_FILES}
import migrate_db
from src.services.database import Database
Database(settings.DB_PATH); migrate_db.apply_v2(settings.DB_PATH)
from src.services.ai_service import AIService
async def fake(self, prompt, schema, role="forms", temperature=None, system=None, images=None):
    if schema.__name__ == "CoverLetter":
        return {"letter": "Dear Hiring Team,\nTest.\nKind regards,\nSimon"}
    if schema.__name__ == "VisionStep":
        bid = re.search(r"'id': '(b\d+)', 'text': 'Confirm", prompt)
        return {"action": "click", "target": bid.group(1) if bid else "", "reason": "x"}
    m = re.search(r"(FIELDS|QUESTIONS):\n(\[.*\])\s*$", prompt, re.S)
    items = json.loads(m.group(2)) if m else []
    out = []
    for it in items:
        opts = it.get("options") or []
        a = ("No" if "No" in opts else opts[-1]) if opts else ("10" if it.get("numeric") else "Some answer text for this question.")
        out.append({"fid": it["fid"], "answer": a, "scope": "global", "confidence": 80, "needs_human": False})
    return {"answers": out}
AIService.structured = fake

from playwright.sync_api import sync_playwright
from src.services.form_engine.engine import FormEngine
from src.services.form_engine.answerer import Answerer
from src.services.appliers import FormRunner, ExternalApplier
from src.services.appliers.base import run_async
from src.services.job_scraper import CARDS_JS

FAIL = []
def check(name, cond, info=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  ({info})" if info and not cond else ""))
    if not cond: FAIL.append(name)

job = {"id": 9, "linkedin_job_id": "r1", "title": "FDE", "company": "Synth", "url": "x", "location": "Auckland, New Zealand", "description": "d", "lane": "fde"}
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome")
    pg = b.new_page(viewport={"width": 1300, "height": 1800})

    pg.goto((ROOT / "tests/fixtures/synthetic_form.html").as_uri())
    snap = FormEngine(pg).scan()
    kinds = {x.text: x.kind for x in snap.buttons}
    check("Apply/Apply with LinkedIn are not submit", kinds.get("Apply") == "apply" and kinds.get("Apply with LinkedIn") == "apply", str(kinds))
    check("real submit picked", snap.button("submit").text == "Submit application")
    rf = next(f for f in snap.fields if f.kind == "file")
    check("resume hint text is not a filename", not rf.filled, repr(rf.value))

    settings.MANUAL_APPROVAL, settings.DRY_RUN = False, False
    settings.EXTERNAL_AUTO_SUBMIT["generic"] = True
    settings.EXTERNAL_READ_TIME_MIN = settings.EXTERNAL_READ_TIME_MAX = 0
    res = ExternalApplier(FormRunner()).apply(pg, job, url=(ROOT / "tests/fixtures/synthetic_form.html").as_uri())
    check("external form submitted once via real button", res.status == "success", f"{res.status} {res.error}")
    check("CV uploaded", any(q["kind"] == "file" and "cv" in str(q["answer"]).lower() for q in res.qa), str([q for q in res.qa if q['kind']=='file']))

    pg.set_content("""<form><h2>Final step</h2><label><input type="checkbox" id="c1" required> I confirm I am legally authorised to work in the United States</label>
      <label><input type="checkbox" id="c2" required> I confirm the information I have provided is true and accurate</label>
      <label for="ext">Phone Extension</label><input id="ext"><label for="ref">Referrer's first name</label><input id="ref">
      <label for="cc">Phone country code</label><select id="cc"><option>Select an option</option><option selected>New Zealand (+64)</option></select>
      <label for="ph">Mobile phone number</label><input id="ph" required></form>""")
    eng = FormEngine(pg); snap = eng.scan()
    ans = Answerer(settings.DB_PATH)
    need = [f for f in snap.fields if not f.filled]
    ctx = {"snapshot_fields": snap.fields}
    out = run_async(ans.answer_fields(need, job, ctx))
    by = {f.text[:30]: out.get(f.fid) for f in need}
    us = next(v for k, v in by.items() if k.startswith("I confirm I am legally"))
    check("US work-rights declaration not auto-ticked", not (us and us.source == "consent"), str(us))
    tr = next(v for k, v in by.items() if k.startswith("I confirm the information"))
    check("plain accuracy declaration ticked", tr and tr.source == "consent" and tr.value == "Yes", str(tr))
    ex = next(v for k, v in by.items() if k.startswith("Phone Extension"))
    check("phone extension not given own number", not (ex and ex.source == "profile"), str(ex))
    rr = next(v for k, v in by.items() if k.startswith("Referrer"))
    check("referrer name not given own name", not (rr and rr.source == "profile"), str(rr))
    ph = next(v for k, v in by.items() if k.startswith("Mobile phone"))
    check("national number when code preselected", ph and ph.value == "211490191", str(ph))

    settings.DRY_RUN, settings.MANUAL_APPROVAL = True, True
    pg.set_content("""<div><h2>Almost done</h2><button onclick="window.__sub=1;document.body.innerHTML='<h2>Thank you for applying</h2>'">Confirm and submit</button><button>Help</button></div>""")
    r = FormRunner().run(pg, job, "generic", auto_submit=True)
    check("dry run never submits", not pg.evaluate("() => !!window.__sub") and r.status == "dry_run", r.status)
    settings.DRY_RUN = False
    settings.MANUAL_APPROVAL = False
    pg.set_content("""<div><h2>Almost done</h2><button onclick="window.__sub=1">Save &amp; Submit</button></div>""")
    s2 = FormEngine(pg).scan()
    check("'Save & Submit' classified submit", s2.buttons[0].kind == "submit", s2.buttons[0].kind)
    pg.set_content("""<div><h2>Step</h2><button onclick="window.__sub=1">Review and submit</button></div>""")
    s3 = FormEngine(pg).scan()
    check("'Review and submit' classified submit", s3.buttons[0].kind == "submit", s3.buttons[0].kind)

    pg.set_content("""<ul><li data-occludable-job-id="4400000001"><a href="/jobs/view/4400000001/">Applied AI Engineer</a><div class="artdeco-entity-lockup__subtitle">Acme</div><ul class="job-card-container__metadata-wrapper"><li>Remote</li></ul><span>Easy Apply</span></li>
      <li data-occludable-job-id="4400000002"><a href="/jobs/view/4400000002/">AI Engineer</a><div class="artdeco-entity-lockup__subtitle">Beta</div><ul class="job-card-container__metadata-wrapper"><li>Sydney</li></ul><span>Applied</span></li></ul>""")
    cards = {c["id"]: c for c in pg.evaluate(CARDS_JS)["jobs"]}
    check("'Applied AI Engineer' card not treated as applied", cards["4400000001"]["applied"] is False)
    check("real Applied badge detected", cards["4400000002"]["applied"] is True)

    # real card markup (Oct 2026): Easy Apply / Applied sit in the card footer, outside the title block
    pg.goto((ROOT / "tests/fixtures/li_search_cards.html").as_uri())
    live = {c["company"]: c for c in pg.evaluate(CARDS_JS)["jobs"]}
    fs, da = live.get("Client Server", {}), live.get("DataAnnotation", {})
    check("live card: title/company/location parsed", fs.get("title") == "Full Stack Developer C# Vue.js - FinTech" and fs.get("location", "").startswith("Christchurch"), str(fs))
    check("live card: Easy Apply in the card footer detected", fs.get("easy") is True and da.get("easy") is False, f"{fs.get('easy')} {da.get('easy')}")
    check("live card: salary parsed", "NZD/yr" in fs.get("salary", ""), str(fs.get("salary")))
    check("live card: posting age read (1 day / 4 hours)", fs.get("age_days") == 1 and da.get("age_days") == 0, f"{fs.get('age_days')} {da.get('age_days')}")
    pg.evaluate("() => { const li = document.createElement('li'); li.className = 'job-card-container__footer-item'; li.textContent = 'Applied'; document.querySelectorAll('.job-card-container__footer-wrapper')[1].appendChild(li); }")
    da = {c["company"]: c for c in pg.evaluate(CARDS_JS)["jobs"]}["DataAnnotation"]
    check("live card: Applied badge in the card footer detected", da["applied"] is True)

    pg.goto((ROOT / "tests/fixtures/li_job.html").as_uri())
    pg.click("#ea"); pg.wait_for_timeout(1200)
    fr = [f for f in pg.frames if f != pg.main_frame][0]
    fr.evaluate("""() => { document.getElementById('fol').parentElement.remove(); for (let i=1;i<=4;i++) document.getElementById('s'+i).style.display = i===4?'block':'none'; const n=document.getElementById('next'); n.textContent='Submit application'; n.setAttribute('aria-label','Submit application'); }""")
    snap = FormEngine(pg, root_selector='div[role="dialog"]', strict_root=True).scan()
    check("review step without fields keeps Submit button", snap.button("submit") is not None, str([x.text for x in snap.buttons]))

    # Easy Apply as a native <dialog open data-testid="dialog"> in the main frame (live markup, Oct 2026)
    from src.services.appliers.linkedin import LinkedInApplier, LI_ROOT
    pg.goto((ROOT / "tests/fixtures/li_easy_apply_dialog.html").as_uri())
    st = LinkedInApplier(FormRunner()).ui_state(pg)
    check("native <dialog> Easy Apply form detected", st["ready"] is True, str({k: st[k] for k in ("ready", "texts")})[:300])
    snap = FormEngine(pg, root_selector=LI_ROOT, strict_root=True).scan()
    labels = [f.text for f in snap.fields]
    check("dialog fields scanned", all(any(l.startswith(x) for l in labels) for x in ("First name", "Last name", "Phone country code", "Mobile phone number", "Email address", "Location (city)")), str(labels))
    check("page search box outside the dialog ignored", not any(l.lower().startswith("search") for l in labels), str(labels))
    check("dialog Next button is 'next', not submit", snap.button("next") is not None and snap.button("submit") is None, str([(x.text, x.kind) for x in snap.buttons]))

    # work-history editor LinkedIn opens for an imported entry with missing dates (live markup, Oct 2026)
    pg.goto((ROOT / "tests/fixtures/li_easy_apply_experience.html").as_uri())
    pg.evaluate("() => { const s = [...document.querySelectorAll('dialog select')].find(e => [...e.options].some(o => o.text === 'May')); const d = document.createElement('div'); d.textContent = 'This field is required'; s.parentElement.appendChild(d); }")
    snap = FormEngine(pg, root_selector=LI_ROOT, strict_root=True).scan()
    month = next((f for f in snap.fields if f.kind == "select" and "May" in f.options), None)
    check("unlabeled month select labelled from placeholder + group", month is not None and month.text == "From (Month)" and "Dates of employment" in month.raw.get("section", ""), str(month and (month.text, month.raw.get("section"))))
    check("inline 'This field is required' is an error, not the label", month is not None and "required" not in month.text.lower() and month.required and bool(month.errors), str(month and (month.text, month.required, month.errors)))
    asked = []
    fake_structured = AIService.structured
    async def spy(self, prompt, schema, *a, **kw):
        asked.append(prompt)
        return await fake_structured(self, prompt, schema, *a, **kw)
    AIService.structured = spy
    ans = run_async(Answerer(settings.DB_PATH).answer_fields(snap.fields, job, {}))
    AIService.structured = fake_structured
    check("work-history fields are never sent to the AI", not any(re.search(r"From \(Month\)|I currently work here|Dates of employment", p) for p in asked), str(asked)[:300])
    check("required work-history date stops for a human", month is not None and ans[month.fid].needs_human and ans[month.fid].value == "", str(month and ans.get(month.fid)))
    # ...unless the candidate gave approximate dates for that entry: filled from the profile and the entry is saved
    from src.services.cv_data import APPLICATION_PROFILE
    from src.services.appliers.linkedin import LinkedInApplier
    saved_dates = APPLICATION_PROFILE.get("work_history_dates", {})
    APPLICATION_PROFILE["work_history_dates"] = {"Example Ltd": {"from": "January 2005", "to": "December 2006"}}
    pg.goto((ROOT / "tests/fixtures/li_easy_apply_experience.html").as_uri())
    pg.evaluate("() => [...document.querySelectorAll('dialog button')].find(x => x.textContent.trim() === 'Save').addEventListener('click', () => { window.__saved = 1; })")
    eng_wh = FormEngine(pg, root_selector=LI_ROOT, strict_root=True)
    done_wh = LinkedInApplier(FormRunner()).fill_known_work_dates(eng_wh, eng_wh.scan())
    vals_wh = pg.evaluate("() => [...document.querySelectorAll('dialog select')].map(s => s.options[s.selectedIndex].text)")
    check("known undated entry gets the profile's dates and is saved", done_wh and vals_wh == ["January", "2005"] and pg.evaluate("() => window.__saved === 1"), f"{done_wh} {vals_wh}")
    APPLICATION_PROFILE["work_history_dates"] = {}
    pg.goto((ROOT / "tests/fixtures/li_easy_apply_experience.html").as_uri())
    eng_wh = FormEngine(pg, root_selector=LI_ROOT, strict_root=True)
    check("unknown undated entry is never given dates", LinkedInApplier(FormRunner()).fill_known_work_dates(eng_wh, eng_wh.scan()) is False)
    APPLICATION_PROFILE["work_history_dates"] = saved_dates

    # Yes/No radios: question in a shared aria-label, "Yes"/"No" in sibling divs, inputs re-rendered after a click (live markup, Oct 2026)
    pg.goto((ROOT / "tests/fixtures/li_easy_apply_questions.html").as_uri())
    eng = FormEngine(pg, root_selector=LI_ROOT, strict_root=True)
    yn = next((f for f in eng.scan().fields if f.kind == "radio"), None)
    check("radio question read from the shared aria-label", yn is not None and yn.text.startswith("Are you either a Citizen or Permanent Resident of Australia"), str(yn and yn.text))
    check("radio options are Yes / No, not the question", yn is not None and yn.options == ["Yes", "No"], str(yn and yn.options))
    check("answering with the question text matches no option", yn is not None and not eng.fill(yn, yn.text)[0] and not pg.evaluate("() => [...document.querySelectorAll('input[type=radio]')].some(r => r.checked)"))
    # like LinkedIn: only the clicked option is replaced by a fresh element
    pg.evaluate("""() => document.querySelectorAll('input[type=radio]').forEach(r => r.addEventListener('click', () => setTimeout(() => {
        const n = r.cloneNode(true); n.removeAttribute('data-lb-fid'); n.removeAttribute('data-lb-opt'); n.id = r.id + 'x'; n.checked = r.checked; r.replaceWith(n);
    }, 50)))""")
    ok, got = eng.fill(yn, "No") if yn else (False, "")
    state = pg.evaluate("() => [...document.querySelectorAll('input[type=radio]')].map(r => r.checked)")
    check("radio fill survives React re-render and ticks only 'No'", ok and state == [False, True], f"ok={ok} got={got} checked={state}")

    # multi-select checkboxes without a name; LinkedIn replaces each clicked input (live, Oct 2026)
    pg.set_content("""<dialog open data-testid="dialog"><div><span>Please select the country or countries where you have working rights:*</span>
      <fieldset aria-describedby="error-message-x">""" + "".join(f'<div><input type="checkbox" id="c{i}"><label for="c{i}">{c}</label></div>' for i, c in enumerate(["Australia", "New Zealand", "Brazil", "Canada", "United States"])) + """</fieldset></div>
      <button>Next</button></dialog>""")
    pg.evaluate("""() => document.querySelectorAll('input[type=checkbox]').forEach(r => r.addEventListener('click', () => setTimeout(() => {
        const n = r.cloneNode(true); n.removeAttribute('data-lb-fid'); n.removeAttribute('data-lb-opt'); n.id = r.id + 'x'; n.checked = r.checked; r.replaceWith(n);
        const l = document.querySelector(`label[for="${r.id}"]`); if (l) l.htmlFor = n.id;
    }, 50)))""")
    eng_cb = FormEngine(pg, root_selector=LI_ROOT, strict_root=True)
    cb = next((f for f in eng_cb.scan().fields if f.kind == "checkbox"), None)
    ok_cb = eng_cb.fill(cb, "Australia; New Zealand")[0] if cb else False
    state = pg.evaluate("() => [...document.querySelectorAll('input[type=checkbox]')].map(r => r.checked)")
    check("unnamed checkbox group survives re-render (AU + NZ ticked, verified)", ok_cb and state == [True, True, False, False, False], f"ok={ok_cb} checked={state}")

    # LinkedIn's own daily Easy Apply cap (live text, Oct 2026): recognised, not treated as a broken form
    pg.set_content("""<a data-view-name="job-apply-button" aria-label="Easy Apply to this job" href="#">Easy Apply</a>
      <dialog open data-testid="dialog"><h2>You reached today’s Easy Apply limit</h2><p>Great effort applying today. We limit Easy Apply submissions to help ensure each application gets the right attention. Save this job and continue applying tomorrow.</p><button>Go</button></dialog>""")
    li_lim = LinkedInApplier(FormRunner())
    st_lim = li_lim.ui_state(pg)
    check("Easy Apply daily-limit dialog recognised", any(re.search(r"reached today.{0,3}s easy apply limit", t, re.I) for t in st_lim["texts"]) and not st_lim["ready"], str(st_lim["texts"])[:200])

    # LinkedIn "Share your profile?" before an external application: Continue is a link (live, Oct 2026)
    pg.set_content("""<button aria-label="Apply on company website">Apply</button>
      <dialog open data-testid="dialog" aria-labelledby="dialog-header"><header id="dialog-header"><h2>Share your profile?</h2></header>
      <p>Increase your chance of being viewed. Share your full profile with the job poster when you click apply.</p>
      <button type="button" aria-label="Dismiss"></button>
      <a href="https://www.linkedin.com/safety/go/?url=https%3A%2F%2Fjob-boards.greenhouse.io%2Fx" target="_blank" onclick="window.__cont=1; return false;">Continue <svg aria-hidden="true"></svg></a></dialog>""")
    li_ap = LinkedInApplier(FormRunner())
    check("share-profile dialog seen as the external hand-off", li_ap.ui_state(pg)["external"] is True)
    clicked = li_ap._click_in_frames(pg, r"^continue\b(?! with)|continue to (apply|site|application)|^apply$|i understand")
    check("share-profile Continue link clicked", clicked and pg.evaluate("() => window.__cont === 1"))
    # sign-in walls: guest route taken, social sign-in never a 'next' button
    pg.set_content("""<form><label for="em">Email</label><input id="em" type="email">
      <button type="button">Continue with email</button><button type="button">Continue with Google</button><button type="button">Continue with Microsoft</button>
      <button type="button" onclick="window.__guest=1">Continue without Account</button></form>""")
    eng_si = FormEngine(pg)
    s_si = eng_si.scan()
    kinds_si = {x.text: x.kind for x in s_si.buttons}
    check("social sign-in buttons are never 'next'", kinds_si.get("Continue with Google") == "social" and kinds_si.get("Continue with Microsoft") == "social", str(kinds_si))
    from src.services.appliers.external import ExternalApplier as _EA
    check("guest route taken when offered", _EA(FormRunner())._take_guest_path(eng_si, s_si) and pg.evaluate("() => window.__guest === 1"))

    # external forms (structures seen live, Oct 2026)
    from src.services.appliers.external import ROOTS
    pg.set_content("""<div class="ashby-job-posting-right-pane"><div role="tabpanel" id="form" aria-labelledby="job-application-form">
      <div class="ashby-application-form-autofill-pane"><input type="file" aria-label="Autofill from resume"></div>
      <div class="ashby-application-form-container"><label for="nm">Name</label><input id="nm" required><label for="em">Email</label><input id="em" type="email" required></div>
      <button class="_button _primary _submit">Submit Application</button></div></div>""")
    s_ab = FormEngine(pg, root_selector=ROOTS["ashby"]).scan()
    check("Ashby: Submit button found beside the fields", s_ab.button("submit") is not None and len(s_ab.fields) >= 2, str([(x.text, x.kind) for x in s_ab.buttons]))
    pg.set_content("""<form id="application-form"><label for="location-input">Current location ✱</label>
      <div><input class="location-input" id="location-input" type="text" name="location" required><input id="selected-location" type="hidden" name="selectedLocation"><div class="dropdown-results"></div></div></form>
      <script>const i = document.getElementById('location-input'), r = document.querySelector('.dropdown-results');
      i.addEventListener('input', () => { r.innerHTML = i.value.length < 3 ? '' : ['Auckland, Auckland, New Zealand', 'Auckland Park, Johannesburg, South Africa'].map(t => `<div class="dropdown-location">${t}</div>`).join(''); });
      r.addEventListener('click', e => { if (e.target.classList.contains('dropdown-location')) { i.value = e.target.textContent; document.getElementById('selected-location').value = JSON.stringify({name: i.value}); r.innerHTML = ''; } });
      i.addEventListener('blur', () => setTimeout(() => { if (!document.getElementById('selected-location').value) i.value = ''; }, 300));</script>""")
    eng_lv = FormEngine(pg, root_selector=ROOTS["lever"], human_typing=False)
    loc_f = next((f for f in eng_lv.scan().fields if "location" in f.text.lower()), None)
    check("Lever: location input without ARIA is an autocomplete", loc_f is not None and loc_f.kind == "combobox", str(loc_f and loc_f.kind))
    ok_lv = eng_lv.fill(loc_f, "Auckland, New Zealand")[0] if loc_f else False
    check("Lever: location picked from the suggestion list", ok_lv and pg.evaluate("() => document.getElementById('selected-location').value") != "", pg.evaluate("() => document.getElementById('location-input').value"))
    pg.set_content("""<form><label for="ai">AI Policy for Application *</label><select id="ai" required><option value="">Select...</option><option>Yes</option><option>No</option></select>
      <label for="nt">As part of our interview process, we may use AI notetakers to record interviews. Do you consent?</label><select id="nt"><option value="">Select...</option><option>Yes, I consent</option><option>No</option></select>
      <label for="pr">Name Pronunciation | How do you pronounce your name?</label><input id="pr"></form>""")
    asked = []
    AIService.structured = spy
    ext_fields = FormEngine(pg).scan().fields
    ans = run_async(Answerer(settings.DB_PATH).answer_fields(ext_fields, job, {}))
    AIService.structured = fake_structured
    by_q = {f.text[:20]: ans.get(f.fid) for f in ext_fields}
    check("AI-use policy never auto-confirmed (needs you)", by_q["AI Policy for Applic"] is not None and by_q["AI Policy for Applic"].needs_human and not any("AI Policy" in p for p in asked), str(by_q["AI Policy for Applic"]))
    check("interview AI-notetaker consent still answered normally", any("notetakers" in p for p in asked))
    check("name pronunciation never invented", by_q["Name Pronunciation |"] is not None and by_q["Name Pronunciation |"].value == "", str(by_q["Name Pronunciation |"]))

    # JobAdder phone box with a select2 flag picker; dropdowns that don't list the candidate's location (Dropbox, Peoplebank)
    from src.services.form_engine.matching import match_option
    check("fuzzy match never turns New Zealand into Netherlands", match_option("New Zealand", ["Australia", "Netherlands", "Other Location"]) is None
          and match_option("Bachelors degree", ["High school", "Bachelor's Degree", "Master's Degree"]) == 1)
    pg.set_content("""<form><label for="CandidateMobile">Mobile</label><div class="phone-number"><div class="flex-row">
      <div class="select2-container country-list"><a class="select2-choice" href="#"><span class="select2-chosen"><span class="flag flag-nz"></span></span></a>
      <label for="s2id_autogen4" class="select2-offscreen"></label><input class="select2-focusser select2-offscreen" type="text" aria-haspopup="true" role="button" id="s2id_autogen4"></div>
      <input class="country-list" style="display: none;"><input class="formatted-number form-control" id="CandidateMobile_FormattedNumber" name="CandidateMobile.FormattedNumber" type="text" required></div></div>
      <label for="loc">Current Location *</label><select id="loc" required><option>Please Select</option><option>Australia</option><option>Netherlands</option><option>US - New Jersey</option><option>Other Location</option></select>
      <label for="st">State/Region *</label><select id="st" required><option>Please Select...</option><option>New South Wales</option><option>Queensland</option><option>Victoria</option></select>
      <label for="ct">Country *</label><select id="ct" required><option>Please Select</option><option>Australia</option><option>New Zealand</option></select></form>""")
    ja_fields = FormEngine(pg).scan().fields
    mob = [f for f in ja_fields if re.search(r"mobile", f.text, re.I)]
    check("JobAdder: select2 helper input is not a field, the phone box is", len(mob) == 1 and mob[0].raw.get("name") == "CandidateMobile.FormattedNumber",
          str([(f.text, f.raw.get("name")) for f in mob]))
    ja = run_async(Answerer(settings.DB_PATH).answer_fields(ja_fields, job, {}))
    by_q = {f.text[:12]: ja.get(f.fid) for f in ja_fields}
    check("location missing from the options -> 'Other Location'", by_q["Current Loca"] is not None and by_q["Current Loca"].value == "Other Location", str(by_q["Current Loca"]))
    check("country dropdown -> New Zealand", by_q["Country *"] is not None and by_q["Country *"].value == "New Zealand", str(by_q["Country *"]))
    check("state list without NZ is left to the bank / AI, not forced", by_q["State/Region"] is None or by_q["State/Region"].source != "profile", str(by_q["State/Region"]))

    # Rippling (Copado, Oct 2026): upload hint is not a file; each site's own "decline" wording
    pg.set_content("""<form><div data-testid="field"><span id="l8">CV</span><span>*</span><div><div id="fi10">Total 0 file selected</div>
      <label data-testid="resume" aria-labelledby="fi10 l8"><input accept=".doc,.docx,.pdf" data-testid="input-resume" type="file">
      <button type="button"><span>Drop or select (.doc / .docx / .pdf)</span></button></label></div></div>
      <div><label for="cl">Cover letter</label><input id="cl" type="file"><div>Simon_CV.pdf</div></div></form>""")
    rp_files = [f for f in FormEngine(pg).scan().fields if f.kind == "file"]
    check("Rippling: '(.doc / .docx / .pdf)' hint and 'Total 0 file selected' mean no file yet", rp_files and not rp_files[0].filled, str([(f.text[:30], f.value) for f in rp_files]))
    check("a real file name beside an upload still counts as attached", len(rp_files) > 1 and rp_files[1].value == "Simon_CV.pdf", str([(f.text[:30], f.value) for f in rp_files]))
    check("decline answers pick each site's decline wording", match_option("Choose not to disclose", ["Male", "Female", "I don't wish to answer"]) == 2
          and match_option("Decline to self-identify", ["Yes", "No", "Prefer not to say"]) == 2 and match_option("No", ["Yes", "No", "Prefer not to say"]) == 1)

    # Ashby (Dovetail, Oct 2026): the submit button spins (disabled) for a while before the confirmation
    pg.set_content("""<form><label for="nm">Full name</label><input id="nm" required>
      <button type="submit" id="sb">Submit Application</button></form>
      <script>document.querySelector('form').onsubmit = e => { e.preventDefault(); const b = document.getElementById('sb');
        b.disabled = true; b.innerHTML = '<span class="spinner"></span> Submit Application'; window.__clicks = (window.__clicks || 0) + 1;
        setTimeout(() => { document.body.innerHTML = '<h2>Thank you for applying</h2><p>Your application was successfully submitted.</p>'; }, 14000); };</script>""")
    res_busy = FormRunner().run(pg, job, "ashby", auto_submit=True)
    check("Ashby: waits out a busy submit button for the confirmation", res_busy.status == "success" and pg.evaluate("() => window.__clicks") == 1,
          f"{res_busy.status} {res_busy.error} clicks={pg.evaluate('() => window.__clicks')}")

    # iCIMS behind a Jibe careers site (GitHub, Oct 2026): Apply -> iCIMS page with a slow iframe -> email + privacy
    # -> new account -> application. Test credentials only; the fake hosts are served locally by page.route.
    import os
    from src.services.appliers.external import detect_ats
    os.environ["ATS_ACCOUNT_EMAIL"], os.environ["ATS_ACCOUNT_PASSWORD"] = "bot@example.test", "test-pass-123"
    ICIMS_IN = """<div id="app"></div><script>
      const app = document.getElementById('app'), $ = id => document.getElementById(id);
      function emailStep() {
        app.innerHTML = `<h2>Enter Your Information</h2><label for="email">Email</label><input type="email" id="email" name="css_loginName">
          <div><b>Consent</b> Please acknowledge that you've read the Candidate Privacy Policy.
          <label for="accept_gdpr"><input type="checkbox" id="accept_gdpr" name="accept_gdpr" aria-required="true"> I accept</label></div>
          <input id="enterEmailSubmitButton" type="submit" value="Next">`;
        $('enterEmailSubmitButton').onclick = e => { e.preventDefault(); if ($('email').value && $('accept_gdpr').checked) { window.__email = $('email').value; CODE ? codeStep() : accountStep(); } };
      }
      function codeStep() { app.innerHTML = `<h2>Verify</h2><p>We've sent a verification code to your email.</p><label for="vc">Verification code</label><input id="vc"><button>Verify</button>`; }
      function accountStep() {
        app.innerHTML = `<h2>Create an Account</h2><label for="fn">First Name</label><input id="fn"><label for="ln">Last Name</label><input id="ln">
          <label for="pw">Password</label><input type="password" id="pw"><label for="pw2">Re-enter Password</label><input type="password" id="pw2"><button id="ca">Create Account</button>`;
        $('ca').onclick = () => { if ($('pw').value && $('pw').value === $('pw2').value && $('fn').value && $('ln').value) { window.__account = [$('fn').value, $('ln').value, $('pw').value]; appStep(); } };
      }
      function appStep() {
        app.innerHTML = `<h2>Candidate Profile</h2><label for="ph">Phone</label><input id="ph" type="tel" required><label for="cv">Resume</label><input type="file" id="cv">
          <input type="submit" id="sub" value="Submit Application">`;
        $('sub').onclick = e => { e.preventDefault(); window.__submitted = 1; app.innerHTML = '<h2>Thank you for applying</h2>'; };
      }
      emailStep();</script>"""
    def icims_route(route):
        u = route.request.url
        if "jibeapply.com" in u:
            body = "<main><h1>Engineer</h1><p>About the role.</p><button onclick=\"location.href='https://careers-acme.icims.com/jobs/1/login'\">Apply</button></main>"
        elif "in_iframe" in u:
            body = ICIMS_IN.replace("CODE ?", ("true" if "/jobs/2/" in u else "false") + " ?")
        else:
            job_no = "2" if "/jobs/2/" in u else "1"
            body = f"<header><a href='#'>Careers</a></header><iframe id='icims_content_iframe' src='https://careers-acme.icims.com/jobs/{job_no}/login?in_iframe=1' height='600'></iframe>"
        route.fulfill(status=200, content_type="text/html", body=body)
    pg.route(re.compile(r"https://(acme\.jibeapply\.com|careers-acme\.icims\.com)/.*"), icims_route)
    check("Jibe career sites are iCIMS", detect_ats("https://githubinc.jibeapply.com/jobs/6297") == "icims")
    settings.EXTERNAL_AUTO_SUBMIT["icims"] = True
    res_ic = ExternalApplier(FormRunner()).apply(pg, job, url="https://acme.jibeapply.com/jobs/1")
    acct, used_email = pg.evaluate("() => window.__account || null"), pg.evaluate("() => window.__email || null")
    check("iCIMS: frame opened as the page, email step, new account, application submitted", res_ic.status == "success" and pg.evaluate("() => window.__submitted") == 1,
          f"{res_ic.status} {res_ic.error} url={pg.url}")
    check("iCIMS: account uses ATS_ACCOUNT_EMAIL/PASSWORD and the profile name",
          used_email == "bot@example.test" and acct == [APPLICATION_PROFILE["first_name"], APPLICATION_PROFILE["last_name"], "test-pass-123"], f"{used_email} {acct}")
    pg.goto("https://careers-acme.icims.com/jobs/2/login")
    res_code = ExternalApplier(FormRunner()).apply(pg, job)
    check("iCIMS: an emailed verification code stops for a human", res_code.status == "manual_review_needed" and "code" in (res_code.error or ""), f"{res_code.status} {res_code.error}")

    # login detection, markup trimmed from live captures (Oct 2026)
    from src.services.browser import linkedin_logged_in
    lg = b.new_context().new_page()
    lg.set_content("""<nav data-testid="primary-nav"><a href="https://www.linkedin.com/mynetwork" aria-label="Network, 2 new notifications">My Network</a>
      <a href="https://www.linkedin.com/messaging/" aria-label="Messaging, 3 new notifications">Messaging</a>
      <a href="https://www.linkedin.com/notifications/" aria-label="Notifications, 25 new notifications">Notifications</a></nav><main>Start a post</main>""")
    check("logged in: newer header (feed, jobs home)", linkedin_logged_in(lg) is True)
    lg.set_content("""<header class="global-nav"><ul class="global-nav__primary-items"><li class="global-nav__primary-item"><span class="global-nav__primary-link-text" title="Notifications">Notifications</span></li>
      <li class="global-nav__primary-item"><div class="global-nav__me artdeco-dropdown"><button class="global-nav__primary-link global-nav__primary-link-me-menu-trigger" type="button">Me</button></div></li></ul></header>""")
    check("logged in: classic header (jobs search)", linkedin_logged_in(lg) is True)
    lg.set_content("""<header class="base-serp-page__header"><nav class="nav" aria-label="Primary"><a href="/?trk=public_jobs_nav-header-logo">LinkedIn</a>
      <a href="https://www.linkedin.com/signup/cold-join">Join now</a><a aria-label="Sign in" href="https://www.linkedin.com/login">Sign in</a></nav></header><main>Ai Engineer in New Zealand</main>""")
    check("logged out: guest jobs page", linkedin_logged_in(lg) is False)
    lg.set_content("<main></main>")
    check("blank page without login cookie is not logged in", linkedin_logged_in(lg) is False)
    lg.context.add_cookies([{"name": "li_at", "value": "x", "domain": ".linkedin.com", "path": "/"}])
    check("blank page with login cookie falls back to logged in", linkedin_logged_in(lg) is True)
    b.close()
print("\nALL PASS" if not FAIL else f"\n{len(FAIL)} FAILED: {FAIL}")
