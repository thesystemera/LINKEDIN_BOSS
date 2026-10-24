import re
import time
import random
import asyncio
from typing import Dict, List, Optional

from pydantic import BaseModel

from src.services.ai_service import AIService
from src.services.cv_data import CV_FULL_TEXT, CV_SUPPLEMENTARY
from src.services.appliers.linkedin import JOB_STATE_JS
from src.services.browser import SessionExpired, linkedin_logged_in
from src.utils.logger import custom_print

DETAILS_JS = """
() => {
  const clean = s => (s || '').replace(/[ \\t]+/g, ' ').replace(/\\n{3,}/g, '\\n\\n').trim();
  const one = s => (s || '').replace(/\\s+/g, ' ').trim();
  let desc = '';
  const heads = [];
  const tw = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, { acceptNode: n => /^\\s*about the job\\s*$/i.test(n.nodeValue) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP });
  while (tw.nextNode()) heads.push(tw.currentNode.parentElement);
  for (const h of heads) {
    let sec = h.parentElement;
    for (let i = 0; i < 4 && sec; i++) {
      const t = clean(sec.innerText);
      if (t.length > 300) { desc = t.replace(/^about the job\\s*/i, ''); break; }
      sec = sec.parentElement;
    }
    if (desc) break;
  }
  if (!desc) {
    const sels = ['[data-testid="expandable-text-box"]', '.jobs-description-content__text', '.jobs-description__content', '.jobs-description', '.show-more-less-html__markup', '#job-details', '[class*="jobs-description"]', '[class*="description"]'];
    for (const s of sels) {
      const best = [...document.querySelectorAll(s)].map(e => clean(e.innerText)).sort((a, b) => b.length - a.length)[0];
      if (best && best.length > 200) { desc = best; break; }
    }
  }
  const top = document.querySelector('.job-details-jobs-unified-top-card__container--two-pane, .jobs-unified-top-card, .job-details-jobs-unified-top-card__primary-description-container, [data-view-name="job-detail-page"], main') || document.body;
  const topText = one(top.innerText).slice(0, 1500);
  const salary = (topText.match(/((NZ|A|US|CA)?\\$|€|£)\\s?[\\d,.]+\\s?[kK]?(\\s?(-|–|to)\\s?((NZ|A|US|CA)?\\$|€|£)?\\s?[\\d,.]+\\s?[kK]?)?\\s?(\\/\\s?(yr|year|hr|hour|day|month)|per (hour|annum|year|day))?/) || [''])[0];
  const workplace = (topText.match(/\\b(Remote|Hybrid|On-site)\\b/) || [''])[0];
  const emp = (topText.match(/\\b(Full-time|Part-time|Contract|Temporary|Internship|Volunteer)\\b/) || [''])[0];
  return { description: desc.slice(0, 9000), salary_text: salary, workplace, employment_type: emp, top: topText.slice(0, 600) };
}
"""


class JobEvaluation(BaseModel):
    apply: bool
    confidence: int
    reason: str
    lane: str = ""
    eligible: bool = True
    blockers: List[str] = []
    employment_type: str = ""
    location: str = ""
    pay_min: Optional[float] = None
    pay_max: Optional[float] = None
    pay_currency: str = ""
    pay_period: str = ""
    pay_estimated: bool = False


class PreFilterResult(BaseModel):
    keep_indices: List[int]


def annual_nzd(min_v, max_v, currency: str, period: str, cfg) -> Optional[float]:
    vals = [v for v in (min_v, max_v) if isinstance(v, (int, float)) and v > 0]
    if not vals:
        return None
    v = sum(vals) / len(vals)
    p = (period or "year").lower()
    if p.startswith("h"):
        v *= cfg.WORK_HOURS_PER_YEAR
    elif p.startswith("d"):
        v *= cfg.WORK_DAYS_PER_YEAR
    elif p.startswith("m"):
        v *= 12
    elif p.startswith("w"):
        v *= 46
    fx = cfg.FX_TO_NZD.get((currency or "NZD").upper(), 1.0)
    return round(v * fx)


class JobEvaluator:
    def __init__(self, config):
        self.config = config
        self.ai_service = AIService()

    def extract_details(self, job: Dict, page) -> Optional[Dict]:
        try:
            if page.url.split("?")[0].rstrip("/") != job["url"].rstrip("/"):
                page.goto(job["url"], wait_until="domcontentloaded")
                time.sleep(random.uniform(2.5, 4.0))
            if not linkedin_logged_in(page):
                raise SessionExpired("LinkedIn session expired")
            for _ in range(2):
                try:
                    page.get_by_role("button", name=re.compile(r"see more|show more", re.I)).first.click(timeout=1500)
                    time.sleep(0.6)
                except Exception:
                    break
            d = page.evaluate(DETAILS_JS)
            st = page.evaluate(JOB_STATE_JS)
            d["apply_type"] = "closed" if st.get("closed") else "applied" if st.get("applied") else "easy" if st.get("easy") else "external" if st.get("ext") else "unknown"
            if len(d.get("description") or "") < 100:
                time.sleep(2)
                d.update({k: v for k, v in page.evaluate(DETAILS_JS).items() if v})
            return d
        except SessionExpired:
            raise
        except Exception as e:
            custom_print("ERROR", f"Could not extract job details: {str(e)[:150]}")
            return None

    async def batch_prefilter_async(self, jobs: List[Dict], db=None) -> List[Dict]:
        if not self.config.USE_PREFILTER or not jobs:
            return jobs
        custom_print("EVALUATING", f"Pre-filtering {len(jobs)} jobs for obvious mismatches...")
        kept: List[Dict] = []
        bs = self.config.PREFILTER_BATCH_SIZE
        for start in range(0, len(jobs), bs):
            batch = jobs[start:start + bs]
            listing = "\n".join(f"{i}. \"{j['title']}\" at {j['company']} ({j.get('location') or ''})" for i, j in enumerate(batch))
            system = """Remove only OBVIOUS mismatches for a senior software / AI / graphics / architecture candidate.
KEEP anything in software engineering, AI/ML, data, cloud/platform, graphics/3D/XR/computer vision, VFX/virtual production, audio/DSP/music and media technology, solutions/forward-deployed/customer engineering, technical leadership, creative technology.
REMOVE: non-tech roles (sales quotas, marketing, finance, HR, healthcare, trades, civil/structural/electrical engineering, teaching), junior/intern/graduate roles, and roles whose title is a different discipline (e.g. "Technical Director - Water Quality").
Return JSON {"keep_indices": [...]} with the indices of the jobs to keep. When in doubt, keep."""
            try:
                res = await self.ai_service.structured(f"Jobs:\n{listing}", PreFilterResult, role="lite", system=system)
                keep = set(res.get("keep_indices", [])) if res else set(range(len(batch)))
            except Exception as e:
                custom_print("WARNING", f"Pre-filter error: {e} - keeping batch")
                keep = set(range(len(batch)))
            for i, j in enumerate(batch):
                if i in keep:
                    kept.append(j)
                else:
                    custom_print("DEBUG", f"Pre-filter removed: {j['title']} at {j['company']}")
                    if db:
                        db.insert_evaluation(j["id"], {"apply": False, "confidence": 0, "reason": "Auto-rejected by pre-filter"})
        custom_print("SUCCESS", f"Pre-filter kept {len(kept)}/{len(jobs)}")
        return kept

    def _eval_system(self) -> str:
        # stable across jobs (cached by Gemini); the job itself goes in the prompt
        lanes = ", ".join(self.config.SEARCH_LANES.keys())
        return f"""Evaluate the job in the prompt for the candidate below. The candidate applies broadly (volume strategy), so approve anything he could credibly do, but flag hard blockers honestly.

CANDIDATE
Based in Auckland, New Zealand. NZ citizen: full work rights in NZ and Australia (no sponsorship). Needs sponsorship anywhere else. Open to remote, NZ/AU relocation, contract or permanent.
Professional years by technology: {CV_SUPPLEMENTARY.get('technology_experience_years', {})}
Current work: {' '.join(str(CV_SUPPLEMENTARY.get('current_work', {}).get('deeppbr_io', {}).get(k, '')) for k in ('role', 'timeframe', 'what_it_is', 'scale'))} Own trained production models: {'; '.join(CV_SUPPLEMENTARY.get('current_work', {}).get('deeppbr_io', {}).get('own_models', {}).get('models', []))}.
How he works: {CV_SUPPLEMENTARY.get('working_style', {}).get('approach', '')}
{CV_FULL_TEXT[:9000]}

RULES
- eligible=false and add to blockers if: remote role restricted to a country/region he can't work in (e.g. "US only", "must reside in EU"), requires citizenship/security clearance he lacks (e.g. AU baseline/NV1, US clearance), requires on-site presence outside NZ/AU without sponsorship, requires fluent non-English language, or is a different discipline entirely.
- Do NOT reject for seniority mismatch alone or missing salary.
- Be factual about skills: if a must-have needs several years of a technology he has little professional use of (compare with the years table), say so in reason and lower confidence; don't pretend.
- confidence 0-100 = realistic chance he'd get past an initial screen.
- lane: one of [{lanes}].
- Pay: if the listing states pay, extract pay_min/pay_max/pay_currency (ISO code)/pay_period (year|month|day|hour) with pay_estimated=false. If not stated, estimate a typical range for this title, level and location with pay_estimated=true.
- employment_type: permanent | contract | temporary | unknown. location: city/country or "Remote (region)".
- apply = eligible and confidence >= 40.
- reason: 1-2 sentences, plain, no flattery.
"""

    async def evaluate_job_async(self, job: Dict, description: str) -> Dict:
        prompt = f"""JOB
Title: {job['title']}
Company: {job['company']}
Location (card): {job.get('location') or 'unknown'} | Workplace: {job.get('workplace') or 'unknown'} | Type: {job.get('employment_type') or 'unknown'} | Stated pay: {job.get('salary_text') or 'not stated'}
Description:
{description[:8000]}
"""
        try:
            res = await self.ai_service.structured(prompt, JobEvaluation, role="eval", system=self._eval_system())
            if not res:
                raise ValueError("empty evaluation")
            res.setdefault("blockers", [])
            if not res.get("eligible", True):
                res["apply"] = False
            res["pay_nzd"] = annual_nzd(res.get("pay_min"), res.get("pay_max"), res.get("pay_currency", ""), res.get("pay_period", ""), self.config)
            res["pay_basis"] = "estimated" if res.get("pay_estimated") else ("stated" if res.get("pay_nzd") else "")
            return res
        except Exception as e:
            custom_print("ERROR", f"AI evaluation error: {e}")
            return {"apply": False, "confidence": 0, "reason": f"API error: {str(e)[:200]}", "error": True}

    last_errors = 0

    def filter_jobs_sync(self, jobs: List[Dict], threshold: int = None, page=None, db=None) -> List[Dict]:
        threshold = self.config.CONFIDENCE_THRESHOLD if threshold is None else threshold
        if self.config.USE_PREFILTER:
            jobs = asyncio.run(self.batch_prefilter_async(jobs, db=db))
            if not jobs:
                return []
        good = []
        self.last_errors = 0
        custom_print("EVALUATING", f"Evaluating {len(jobs)} jobs (reading each description)")
        for idx, job in enumerate(jobs):
            print(f"\n[{idx + 1}/{len(jobs)}] {job['title']} @ {job['company']}")
            if db and job.get("company") and db.recent_duplicate(job["company"], job["title"], self.config.REPOST_COOLDOWN_DAYS, exclude_job_id=job["id"]):
                custom_print("SKIP", "Same company + title applied recently (repost) - skipping")
                db.insert_evaluation(job["id"], {"apply": False, "confidence": 0, "reason": "Repost of a role already applied to"})
                continue
            if idx:
                time.sleep(random.uniform(2, 5))
            details = self.extract_details(job, page) if page else None
            if not details or len(details.get("description") or "") < 100:
                custom_print("ERROR", f"No description for '{job['title']}' - skipping")
                if db:
                    db.insert_evaluation(job["id"], {"apply": False, "confidence": 0, "reason": "No job description available"})
                    if details:
                        db.update_job_details(job["id"], {"apply_type": details.get("apply_type")})
                continue
            job.update({k: v for k, v in details.items() if v and k != "top"})
            if db:
                db.update_job_details(job["id"], details)
            if details.get("apply_type") in ("closed", "applied"):
                custom_print("SKIP", f"Job is {details['apply_type']} - skipping")
                if db:
                    db.insert_evaluation(job["id"], {"apply": False, "confidence": 0, "reason": f"Job {details['apply_type']} on LinkedIn"})
                continue
            if details.get("apply_type") == "external" and (not self.config.EXTERNAL_APPLY or self.config.EASY_APPLY_ONLY):
                custom_print("SKIP", "External application (external applying is off)")
                if db:
                    db.insert_evaluation(job["id"], {"apply": False, "confidence": 0, "reason": "External application - external applying off"})
                continue
            ev = asyncio.run(self.evaluate_job_async(job, details["description"]))
            job["evaluation"] = ev
            if ev.get("error"):
                self.last_errors += 1
                if self.last_errors >= 3 and self.last_errors > len(good):
                    custom_print("ERROR", "Repeated Gemini errors - stopping evaluation (jobs stay unevaluated for the next run)")
                    break
                continue
            ev["apply"] = bool(ev.get("apply")) and int(ev.get("confidence") or 0) >= threshold
            if db:
                db.insert_evaluation(job["id"], ev)
            pay = f" | ~NZ${ev['pay_nzd']:,.0f} ({ev.get('pay_basis')})" if ev.get("pay_nzd") else ""
            if ev.get("apply"):
                good.append(job)
                custom_print("MATCH", f"✓ APPLY {ev.get('confidence')}% [{ev.get('lane', '')}] {details.get('apply_type')}{pay}: {ev.get('reason', '')[:160]}")
            else:
                why = "; ".join(ev.get("blockers") or []) or ev.get("reason", "")
                custom_print("SKIP", f"✗ SKIP {ev.get('confidence')}%{pay}: {why[:180]}")
        custom_print("SUCCESS", f"{len(good)} matches out of {len(jobs)} (threshold {threshold}%)")
        return good
