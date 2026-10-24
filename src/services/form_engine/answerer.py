import re
import json
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from src.config import settings
from src.services.ai_service import AIService
from src.services.answer_bank import AnswerBank, CHOICE_KINDS
from src.services.cv_data import CV_SUPPLEMENTARY, CV_FULL_TEXT, APPLICATION_PROFILE
from src.services.documents import file_purpose, cv_path, cv_text, write_cover_letter
from src.services.form_engine.engine import Field
from src.services.form_engine.matching import match_option, norm, DECLINE_RE
from src.utils.logger import custom_print

EEO_RE = re.compile(r"\b(gender|sex\b|race|racial|ethnic|ethnicity|hispanic|latin[oa]|veteran|disabilit|sexual orientation|transgender|pronoun|aboriginal|torres strait|lgbt|religio|caste|marital)", re.I)
# LinkedIn's work-history / education editors hold the candidate's real history (imported from the profile): never guessed
PROFILE_ENTRY_RE = re.compile(r"edit (experience|education)|dates of employment|i currently work here|dates attended|add (work )?experience|add education", re.I)
# employer policies on using AI to apply: the application is AI-assisted, so agreeing to them would be untrue
AI_POLICY_RE = re.compile(r"\bAI (policy|guidelines?|usage|use)\b.{0,60}\b(application|applying|candidates?)\b|\b(application|candidates?)\b.{0,60}\bAI (policy|guidelines?)\b|use of (AI|artificial intelligence) (in|during|for) (your|the|this) application", re.I)
CONSENT_RE = re.compile(r"\b(i (agree|acknowledge|consent|confirm|certify|declare|understand|have read)|privacy (policy|notice|statement)|terms (and|&) conditions|terms of (use|service)|data (processing|protection)|true and (correct|accurate)|accurate and complete)", re.I)
MARKETING_RE = re.compile(r"(follow .* to stay up to date|job alerts?|newsletter|marketing|subscribe|keep me (updated|informed)|talent (community|network|pool)|future (job )?(opportunities|roles|openings|positions|vacancies)|e-?mail me about|contact me about (future|other))", re.I)
LONGFORM_RE = re.compile(r"(cover letter|^\s*(prompt:\s*)?why\b|why (do you|are you|would you|us|this|join)|tell us|describe|explain|motivat|what (excites|interests|attracts)|additional information|anything else|summary|about yourself|proudest|example of|walk us through)", re.I)
SKIP_PROFILE_RE = re.compile(r"(company name|employer name|\breference|\breferee|\breferr|manager|supervisor|emergency|school|university|college|extension|\bext\b|recruiter|hiring contact)", re.I)
DECLARATION_RISK_RE = re.compile(r"(authori[sz]ed|right to work|work rights|eligib|citizen|resident|visa|sponsor|clearance|security vetting|licen[cs]e|criminal|convict|offen[cs]e|degree|qualification|graduat|years|experience|certified|certification|hold a|hold an|possess|vaccinat|medical|drug|relocat|willing to|able to|available|own (a )?(car|vehicle)|background check|non-?compete|notice)", re.I)

HYPE_WORDS = ["exceptional", "world-class", "visionary", "industry titans", "hedge fund", "prodigy", "passionate", "thrilled",
              "rockstar", "ninja", "guru", "game-changing", "revolutionary", "unparalleled", "cutting-edge", "synergy"]
# phrases that make written answers read as AI-generated
AI_TELLS = ["excited to", "I am excited", "aligns with", "align with", "leverage", "proven track record", "delve", "furthermore", "moreover",
            "in today's", "fast-paced", "dynamic", "unique blend", "testament to", "I am confident", "commitment to", "deeply", "seamless", "robust"]
WRITING_RULES = f"""WRITING (it must read like the candidate wrote it, not a model)
- Write like a senior engineer talking to another engineer: plain words, short sentences, contractions are fine, New Zealand English, first person.
- Sell what an engineering manager cares about: he builds complete products on his own, front end to back end to deployment, with sign-in, payments, tests and polish. Name the real project, what he built in it and what is live. Lead with deepPBR.io (current work) when it fits the job.
- Numbers only when concrete and checkable (lines of code, automated tests, models he trained, Steam reviews, grants, years). Never quote latency, speed-ups, accuracy, or estimated or percentage savings, even where the data mentions them.
- Never use: {', '.join(HYPE_WORDS + AI_TELLS)}. No buzzword lists, no corporate filler, no summary sentence at the end.
- Plain punctuation only: no em or en dashes, no curly quotes, no semicolon chains, no bullet points unless asked.
- Never claim he read, watched, used, attended or spoke to something (a company's product, blog, video, event, people) unless the data says so. If asked about it, say what in it connects to his work, as interest, not as something he did."""
_PUNCT = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "…": "...", " ": " "})


def humanize(text: str) -> str:
    """Strip typographic tells from AI-written text: dashes as punctuation, curly quotes, ellipsis characters."""
    t = str(text).translate(_PUNCT)
    t = re.sub(r"\s*[—–]\s*(?=\w)", ", ", t)
    t = re.sub(r"\s*[—–]\s*", " - ", t)
    return re.sub(r",\s*,", ",", t)


@dataclass
class Answer:
    value: Any
    source: str
    confidence: int = 90
    needs_human: bool = False
    scope: str = "global"

    def tag(self) -> str:
        return {"profile": "profile", "bank": "saved", "bank-pending": "saved-unreviewed", "ai": "AI", "ai-long": "AI-written",
                "file": "file", "eeo": "decline", "consent": "consent", "default": "default"}.get(self.source, self.source)


class ShortAnswer(BaseModel):
    fid: str
    answer: str
    scope: str = "global"
    confidence: int = 70
    needs_human: bool = False


class ShortAnswers(BaseModel):
    answers: List[ShortAnswer]


class LongAnswer(BaseModel):
    fid: str
    answer: str


class LongAnswers(BaseModel):
    answers: List[LongAnswer]


class CoverLetter(BaseModel):
    letter: str


def job_region(job: Dict) -> str:
    text = " ".join(str(job.get(k) or "") for k in ("location", "search_location", "title", "company")) + " " + str(job.get("description") or "")[:1500]
    t = text.lower()
    if re.search(r"new zealand|auckland|wellington|christchurch|hamilton|dunedin|tauranga|\bnz\b|aotearoa", t):
        return "NZ"
    if re.search(r"australia|sydney|melbourne|brisbane|perth|adelaide|canberra|\bnsw\b|victoria|queensland|\bact\b", t):
        return "AU"
    if re.search(r"united states|\busa\b|\bus\b|san francisco|new york|seattle|remote - us|, ca\b|, ny\b|, wa\b|, tx\b", t):
        return "US"
    if re.search(r"united kingdom|\buk\b|london|manchester|edinburgh", t):
        return "UK"
    if re.search(r"singapore", t):
        return "SG"
    if re.search(r"germany|france|netherlands|spain|ireland|europe|\beu\b|berlin|paris|amsterdam|dublin", t):
        return "EU"
    return "OTHER"


class Answerer:
    def __init__(self, db_path: str = None):
        self.ai = AIService()
        self.bank = AnswerBank(db_path or settings.DB_PATH)
        self.p = APPLICATION_PROFILE

    def _decline_option(self, f: Field) -> Optional[str]:
        for o in f.options or []:
            if DECLINE_RE.search(o):
                return o
        return None

    def _profile_answer(self, f: Field, ctx: Dict) -> Optional[Answer]:
        t = f.text.lower()
        lab = (f.label or "").lower()
        ac = (f.raw.get("autocomplete") or "").lower()
        name = (f.raw.get("name") or "").lower()
        p = self.p
        kind = f.kind

        if kind in ("radio", "checkbox", "select", "combobox", "toggle") and EEO_RE.search(t) and settings.EEO_POLICY == "decline":
            opt = self._decline_option(f)
            if opt:
                return Answer(opt, "eeo")
            if kind == "combobox" and not f.options:
                return Answer("Decline to self-identify", "eeo", 60)
            if not f.required:
                return Answer("", "eeo")
            return None

        if kind == "checkbox" and (f.raw.get("single") or len(f.options) == 1):
            if MARKETING_RE.search(t):
                return Answer("Yes" if f.required else "No", "default")      # opt in only when the form insists
            if CONSENT_RE.search(t) and not DECLARATION_RISK_RE.search(t):
                return Answer("Yes", "consent")
        # the same consent / marketing questions as Yes-No choices (terms and conditions are accepted, per the candidate)
        if kind in ("radio", "select", "toggle", "combobox") and f.options and (MARKETING_RE.search(t) or (CONSENT_RE.search(t) and not DECLARATION_RISK_RE.search(t))):
            want_yes = not MARKETING_RE.search(t) or f.required
            rx = r"^(yes|i agree|agree|accept|i accept|i acknowledge|i consent|i have read)\b" if want_yes else r"^(no|decline|do not|don't)\b"
            opt = next((o for o in f.options if re.search(rx, o.strip(), re.I)), None)
            if opt:
                return Answer(opt, "consent" if want_yes else "default")

        if re.search(r"pronounc", t):
            return Answer(p.get("name_pronunciation", ""), "profile")

        if kind in ("text", "combobox", "select") and not SKIP_PROFILE_RE.search(t):
            if ac == "given-name" or re.search(r"^(legal )?first name|given name|^first\b|first name", lab):
                return Answer(p["first_name"], "profile")
            if re.search(r"preferred (first )?name|what would you like us to call you|nickname", t):
                return Answer(p["preferred_name"], "profile")
            if ac == "family-name" or re.search(r"last name|surname|family name", lab):
                return Answer(p["last_name"], "profile")
            if re.search(r"middle name", lab):
                return Answer("", "profile")
            if ac == "name" or re.fullmatch(r"\s*(full |legal |your )?name\s*[*✱]?\s*", lab) or name in ("name", "full_name", "_systemfield_name"):
                return Answer(f"{p['first_name']} {p['last_name']}", "profile")
            if ac == "email" or f.raw.get("inputType") == "email" or (re.search(r"e-?mail", lab) and not MARKETING_RE.search(t) and not re.search(r"e-?mail (me|updates|alerts)", lab)):
                return Answer(p["email"], "profile")
            if re.search(r"(phone|dial|calling) ?(country )?code|country code|phone country", t):
                return Answer(f"{p['phone_country']} ({p['phone_country_code']})", "profile")
            if ac in ("tel", "tel-national") or re.search(r"phone|mobile|cell", lab) or f.raw.get("inputType") == "tel":
                if re.search(r"type|device", lab):
                    return Answer("Mobile", "profile")
                return Answer(p["phone_national"] if ctx.get("has_phone_code_field") else p["phone_e164"], "profile")
            if re.search(r"linkedin", t):
                return Answer(p["linkedin"], "profile")
            if re.search(r"github", t):
                return Answer(p["github"], "profile")
            if re.search(r"portfolio|personal (web)?site|^website|website url|^url|other website|blog", lab):
                return Answer(p["portfolio"], "profile")
            if re.search(r"^(current )?(location|city)\b|location \(city\)|city of residence|where are you (currently )?(based|located)|current location|^town|home city", lab):
                return Answer(p["location"], "profile")
            if re.search(r"^country\b|country of residence|country you (live|reside)|current country", lab):
                return Answer(p["country"], "profile")
            if re.search(r"^(state|region|province|county)\b", lab):
                return Answer(p["region"], "profile")
            if re.search(r"current (company|employer)|most recent (company|employer)|current organi[sz]ation", t):
                return Answer(p["current_company"], "profile")
            if re.search(r"current (job )?title|current role|current position|most recent (job )?title", t):
                return Answer(p["current_title"], "profile")
            if re.search(r"how did you (hear|find|learn)|where did you (hear|see|find|learn)|source of (application|referral)|referral source", t):
                return Answer(p["how_heard"], "profile")
            if re.search(r"street|address|postal code|post ?code|zip|suburb", lab) and not re.search(r"e-?mail|web|url|\bip\b", lab):
                if re.search(r"address line ?2|line 2|apartment|suite", lab):
                    return Answer("", "profile")
                if re.search(r"postal code|post ?code|zip", lab):
                    v = p.get("postcode")
                elif re.search(r"suburb|district|neighbou?rhood", lab):
                    v = p.get("suburb")
                elif re.search(r"street|address line|line 1", lab):
                    v = p.get("street_address")
                else:  # one "Address" field wants the whole address
                    v = p.get("full_address")
                if v:
                    return Answer(v, "profile")
                return Answer("", "profile", 0, needs_human=bool(f.required))
        return None

    def _fit_choice(self, f: Field, a: Answer) -> Optional[Answer]:
        """A profile fact for a dropdown must be one of its options: the fact itself, else the country
        ("Auckland, New Zealand" -> "New Zealand"), else "Other ..." on a location question. None lets the bank / AI choose."""
        opts = [o for o in f.options if o != f.raw.get("placeholderOption") and not re.match(r"^\s*(please )?(select|choose)\b|^\s*-+", o, re.I)]
        if match_option(a.value, opts) is not None:
            return a
        country = self.p.get("country")
        i = match_option(country, opts) if country and country != a.value else None
        if i is not None:
            return Answer(opts[i], a.source, a.confidence)
        other = next((o for o in opts if re.match(r"^\s*other\b", o, re.I)), None)
        if other and re.search(r"location|country|city|region|state|province|based|reside", f.text, re.I):
            return Answer(other, a.source, 80)
        custom_print("FORM", f"– '{f.text[:50]}': profile answer '{a.value}' is not one of the options, asking the bank / AI")
        return None

    async def _file_answer(self, f: Field, job: Dict, ctx: Dict) -> Optional[Answer]:
        if re.search(r"autofill|auto-fill|parse|import from", f"{f.label} {f.question}", re.I) and not f.required:
            return Answer("", "file")
        purpose = file_purpose(f"{f.label} {f.question} {f.raw.get('context', '')}")
        if purpose == "unknown" and re.search(r"resume|cv", (f.raw.get("name") or "") + (f.raw.get("elId") or ""), re.I):
            purpose = "cv"
        if purpose == "unknown" and ctx.get("first_file_is_cv") and not ctx.get("cv_done"):
            purpose = "cv"
        if purpose == "cv":
            p = cv_path(job.get("lane"))
            if p:
                ctx["cv_done"] = True
                return Answer(str(p), "file")
            return Answer("", "file", 0, needs_human=bool(f.required))
        if purpose == "cover_letter":
            if not (f.required or settings.GENERATE_COVER_LETTERS):
                return Answer("", "file")
            letter = ctx.get("cover_letter_text") or await self.cover_letter(job)
            ctx["cover_letter_text"] = letter
            if not letter:
                return Answer("", "file", 0, needs_human=bool(f.required))
            path = write_cover_letter(job, letter)
            return Answer(str(path), "file") if path else Answer("", "file", 0, needs_human=bool(f.required))
        return Answer("", "file", 0, needs_human=bool(f.required))

    def _is_longform(self, f: Field) -> bool:
        if f.kind != "textarea":
            return False
        ml = f.raw.get("maxlength")
        if isinstance(ml, int) and 0 < ml < 150:
            return False
        return bool(LONGFORM_RE.search(f.text))

    def _candidate_blob(self, lane: Optional[str] = None) -> str:
        sup = dict(CV_SUPPLEMENTARY)
        if not settings.MENTION_APPLICATION_BOT:
            exp = dict(sup.get("supplementary_experience", {}))
            exp.pop("meta_automation", None)
            sup["supplementary_experience"] = exp
            skills = dict(sup.get("supplementary_skills", {}))
            skills.pop("meta", None)
            sup["supplementary_skills"] = skills
        uploaded = cv_text(lane)
        cv_part = f"CV BEING SUBMITTED (what the employer sees - keep answers consistent with it):\n{uploaded}" if uploaded else f"CV:\n{CV_FULL_TEXT}"
        return f"CANDIDATE DATA (JSON, source of truth):\n{json.dumps(sup, indent=1)}\n\nAPPLICATION PROFILE:\n{json.dumps(self.p, indent=1)}\n\n{cv_part}"

    def _job_blob(self, job: Dict, region: str) -> str:
        return (f"JOB: {job.get('title')} at {job.get('company')}\nLocation: {job.get('location') or job.get('search_location') or 'unknown'} (region {region})\n"
                f"Employment type: {job.get('employment_type') or 'unknown'}\nStated pay: {job.get('salary_text') or 'not stated'}\n"
                f"Description:\n{str(job.get('description') or 'No description available')[:6000]}")

    async def _ai_short(self, fields: List[Field], job: Dict, region: str, ctx: Dict, error_notes: Dict[str, List[str]] = None) -> Dict[str, Answer]:
        if not fields:
            return {}
        today = date.today()
        items = []
        for f in fields:
            s = f.summary()
            if error_notes and f.fid in error_notes:
                s["validation_errors"] = error_notes[f.fid]
                s["previous_answer"] = ctx.get("previous", {}).get(f.fid)
            items.append(s)
        # stable rules + candidate data first (cached by Gemini); dates, job and fields after
        system = f"""You are filling in a job application form for the candidate below. Answer every field in FIELDS.

RULES
1. Truth only. Use only facts in CANDIDATE DATA / APPLICATION PROFILE / CV. Never invent employers, degrees, certifications, licences, clearances, addresses, referees, ID numbers or metrics. Education questions: use APPLICATION PROFILE "education" (pick the closest option, e.g. "Other" when SAE Institute is not listed).
2. Years-of-experience questions: use technology_experience_years (professional years). Not listed: estimate conservatively from project dates; no real work experience = 0. Whole numbers unless the field shows decimal=true.
3. Yes/No capability questions ("Do you have experience with X?"): Yes only if the CV shows genuine hands-on work with X (or a direct equivalent). Otherwise No.
4. Choice fields (fields with "options"): answer with the exact text of one option. Checkbox groups / multi-selects: every option that applies, separated by "; ". Comboboxes without options: give the plain value to type.
5. Work rights: New Zealand citizen living in Auckland. Full work rights in NZ; NZ citizens can live and work in Australia without sponsorship (Special Category Visa 444). Every other country needs sponsorship. The job's region is given under JOB. Willing to relocate to Australia; open to remote.
6. Salary: follow salary_strategy. Single whole number in the job's local currency (no symbols) unless the field asks otherwise or offers ranges. If the listing states pay, stay inside it.
7. Dates: use TODAY and EARLIEST START DATE from the prompt (YYYY-MM-DD for date inputs, otherwise natural format). Notice period: available immediately.
8. Diversity / EEO questions: pick the "prefer not to say" style option when it exists.
9. A REQUIRED field asking for information that is not in the data (street address, referees, ID numbers, criminal record details, etc.): answer "" and needs_human=true. Optional fields without a grounded answer: answer "".
10. Short fields get short answers (1 line). Never put essay text in a text field. Textareas in this list want a concise factual answer (max 3 sentences, e.g. "None." for declarations that don't apply). Write free text like a person: plain words, no em dashes, never "excited", "aligns with", "leverage", "passionate".
11. If a field shows validation_errors, fix the answer so it satisfies the message (format, range, whole number).
12. scope: "global" if the answer is true for any job (years with Python, languages, name), "region" if it depends on the job's country (work rights, sponsorship, relocation, salary currency), "job" if specific to this employer/listing (salary for this role, previously worked here, why this company).
13. confidence: 0-100 for how well the answer is grounded in the data.

{self._candidate_blob(job.get('lane'))}"""
        prompt = f"""TODAY: {today.isoformat()}
EARLIEST START DATE: {(today + timedelta(days=14)).isoformat()}

{self._job_blob(job, region)}

FIELDS:
{json.dumps(items, indent=1, ensure_ascii=False)}
"""
        res = await self.ai.structured(prompt, ShortAnswers, role="forms", system=system)
        out: Dict[str, Answer] = {}
        if not res:
            return out
        ids = {f.fid for f in fields}
        for a in res.get("answers", []):
            fid = a.get("fid")
            if fid in ids:
                out[fid] = Answer(humanize(a.get("answer", "")), "ai", int(a.get("confidence", 70) or 70), bool(a.get("needs_human")), a.get("scope", "global") or "global")
        return out

    async def _ai_long(self, fields: List[Field], job: Dict, region: str) -> Dict[str, Answer]:
        if not fields:
            return {}
        items = [{"fid": f.fid, "question": f.text[:600], "maxlength": f.raw.get("maxlength"), "required": f.required} for f in fields]
        system = f"""Write answers to the long-form application questions in the prompt for the candidate, in his voice (first person, New Zealand English).

{WRITING_RULES}

STYLE
- Tie 2-3 real projects/skills from the data directly to what this job needs: what he built, alone, and what is live. No claims beyond the data.
- 90-180 words per answer unless maxlength is smaller (stay under maxlength characters).
- {"Do not mention that this application was automated or AI-assisted." if not settings.MENTION_APPLICATION_BOT else "You may mention the candidate built his own AI application tooling if relevant."}
- No greeting or sign-off unless the field is a cover letter. No placeholders.
- Follow the disclosure_strategy in the candidate data for accessibility topics.

{self._candidate_blob(job.get('lane'))}"""
        prompt = f"""{self._job_blob(job, region)}

QUESTIONS:
{json.dumps(items, indent=1, ensure_ascii=False)}
"""
        res = await self.ai.structured(prompt, LongAnswers, role="pro", temperature=0.5, system=system)
        out = {}
        ids = {f.fid for f in fields}
        for a in (res or {}).get("answers", []):
            if a.get("fid") in ids:
                out[a["fid"]] = Answer(humanize(a.get("answer", "")), "ai-long", 80, False, "job")
        return out

    async def cover_letter(self, job: Dict) -> str:
        region = job_region(job)
        system = f"""Write a cover letter for the job in the prompt. First person, New Zealand English, 220-320 words.
Open with "Dear Hiring Team," and close with "Kind regards,\\nSimon Che de Boer".
Structure: why this role (1-2 sentences tied to the listing); 2 short paragraphs on what he has built end to end that this job needs (the product, the parts he built alone, what is live) and one hard problem he solved that is relevant; availability and location (Auckland, NZ; open to remote/relocation where relevant); close.
No claims beyond the data. {"Do not mention that this application was automated or AI-assisted." if not settings.MENTION_APPLICATION_BOT else ""}

{WRITING_RULES}
Follow the disclosure_strategy in the candidate data for accessibility topics.

{self._candidate_blob(job.get('lane'))}"""
        try:
            res = await self.ai.structured(self._job_blob(job, region), CoverLetter, role="pro", temperature=0.5, system=system)
            return humanize((res or {}).get("letter", "")).strip()
        except Exception as e:
            custom_print("ERROR", f"Cover letter generation failed: {e}")
            return ""

    def _needs_answer(self, f: Field) -> bool:
        if f.errors or f.invalid:
            return True
        if f.kind == "file":
            return not f.filled and (f.required or file_purpose(f"{f.label} {f.question}") in ("cv", "cover_letter"))
        if f.kind in ("radio", "checkbox", "toggle", "select", "combobox"):
            return not f.filled
        return not f.filled

    async def answer_fields(self, fields: List[Field], job: Dict, ctx: Dict) -> Dict[str, Answer]:
        region = job_region(job)
        ctx.setdefault("region", region)
        ctx["has_phone_code_field"] = any(re.search(r"country code|phone country|dial code", f.text, re.I) for f in (ctx.get("snapshot_fields") or fields))
        files = [f for f in fields if f.kind == "file"]
        ctx["first_file_is_cv"] = bool(files) and file_purpose(f"{files[0].label} {files[0].question}") == "unknown"
        out: Dict[str, Answer] = {}
        todo = [f for f in fields if self._needs_answer(f)]
        for f in todo:
            if re.search(r"(deselect|select) resume", f.label or "", re.I):
                continue
            if f.kind == "file":
                a = await self._file_answer(f, job, ctx)
                if a:
                    out[f.fid] = a
                continue
            if PROFILE_ENTRY_RE.search(f"{f.raw.get('section') or ''} {f.text}"):
                custom_print("FORM", f"– work history / education entry '{f.text[:50]}' is never guessed{' - needs you' if f.required else ''}")
                out[f.fid] = Answer("", "human", 0, bool(f.required))
                continue
            if AI_POLICY_RE.search(f.text):
                custom_print("FORM", f"– '{f.text[:50]}' asks you to agree to an AI-use policy - never auto-confirmed{' - needs you' if f.required else ''}")
                out[f.fid] = Answer("", "human", 0, bool(f.required))
                continue
            a = self._profile_answer(f, ctx)
            if a and a.source == "profile" and a.value and f.kind in CHOICE_KINDS and f.options:
                a = self._fit_choice(f, a)
            if a:
                out[f.fid] = a
                continue
            if f.kind == "textarea" and self._is_longform(f):
                continue
            opts = [o for o in (f.options or []) if o != f.raw.get("placeholderOption")]
            hit = self.bank.lookup(f.text, f.kind, opts, region, settings.ANSWER_BANK_REUSE_PENDING)
            if hit:
                out[f.fid] = Answer(hit["answer"], "bank" if hit["status"] == "approved" else "bank-pending", 90, False, hit["scope"])
        rest_short = [f for f in todo if f.fid not in out and f.kind != "file" and not (f.kind == "textarea" and self._is_longform(f)) and not re.search(r"(deselect|select) resume", f.label or "", re.I)]
        rest_long = [f for f in todo if f.fid not in out and f.kind == "textarea" and self._is_longform(f)]
        rest_long = [f for f in rest_long if f.required or settings.FILL_OPTIONAL_LONGFORM or re.search(r"cover letter", f.text, re.I)]
        for f in rest_long:
            ml = f.raw.get("maxlength")
            if re.search(r"cover letter", f.text, re.I) and (ml if isinstance(ml, int) and ml > 0 else 5000) >= 1200:
                letter = ctx.get("cover_letter_text") or await self.cover_letter(job)
                ctx["cover_letter_text"] = letter
                if letter:
                    out[f.fid] = Answer(letter, "ai-long", 80, False, "job")
        rest_long = [f for f in rest_long if f.fid not in out]
        try:
            out.update(await self._ai_short(rest_short, job, region, ctx))
        except Exception as e:
            custom_print("ERROR", f"AI short-answer call failed: {e}")
        try:
            out.update(await self._ai_long(rest_long, job, region))
        except Exception as e:
            custom_print("ERROR", f"AI long-answer call failed: {e}")
        pending = ctx.setdefault("bank_pending", {})
        for f in rest_short:
            a = out.get(f.fid)
            if a and a.source == "ai" and not a.needs_human and str(a.value).strip():
                opts = [o for o in (f.options or []) if o != f.raw.get("placeholderOption")]
                if f.kind in CHOICE_KINDS and opts and match_option(a.value, opts) is None:
                    continue
                pending[f.text] = (f.text, f.kind, opts, a.value, a.scope, region)
        return out

    def commit_bank(self, ctx: Dict):
        for row in (ctx.get("bank_pending") or {}).values():
            q, kind, options, value, scope, region = row[:6]
            source = row[6] if len(row) > 6 else "ai"
            self.bank.store(q, kind, options, value, scope, region, source, status="approved" if source == "you" else "pending")
        ctx["bank_pending"] = {}

    def discard(self, f: Field, ctx: Dict):
        (ctx.get("bank_pending") or {}).pop(f.text, None)
        self.bank.demote(f.text, f.kind, ctx.get("region", ""))

    async def fix_errors(self, fields: List[Field], previous: Dict[str, Answer], job: Dict, ctx: Dict) -> Dict[str, Answer]:
        region = ctx.get("region") or job_region(job)
        bad = [f for f in fields if f.errors or f.invalid]
        if not bad:
            return {}
        notes = {f.fid: (f.errors or ["invalid value"]) for f in bad}
        ctx["previous"] = {fid: (a.value if isinstance(a, Answer) else a) for fid, a in previous.items()}
        short = [f for f in bad if f.kind not in ("file",) and not PROFILE_ENTRY_RE.search(f"{f.raw.get('section') or ''} {f.text}")]
        for f in bad:
            self.discard(f, ctx)
        res = await self._ai_short(short, job, region, ctx, notes)
        pending = ctx.setdefault("bank_pending", {})
        for f in short:
            a = res.get(f.fid)
            if a and str(a.value).strip() and not a.needs_human:
                pending[f.text] = (f.text, f.kind, list(f.options or []), a.value, a.scope, region)
        return res

    def remember(self, f: Field, value: Any, region: str, scope: str = "global"):
        self.bank.store(f.text, f.kind, f.options or [], value, scope, region, "you")
