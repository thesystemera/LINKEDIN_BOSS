import time
import asyncio
from typing import Dict, List
from pydantic import BaseModel

from src.services.ai_service import AIService
from src.services.cv_data import CV_FULL_TEXT
from src.utils.logger import custom_print


class JobEvaluation(BaseModel):
    apply: bool
    confidence: int
    reason: str


class PreFilterResult(BaseModel):
    keep_indices: List[int]


class JobEvaluator:
    def __init__(self, config):
        self.config = config
        self.ai_service = AIService()
        self._initialized = False

    async def _ensure_initialized(self):
        if not self._initialized:
            await self.ai_service.initialize()
            self._initialized = True

    def _extract_job_description(self, job: Dict, page) -> str:
        try:
            if page.url != job['url']:
                page.goto(job['url'])
                time.sleep(3)  # Give more time for dynamic content

            # Try multiple selector strategies (updated Jan 2026)
            selectors = [
                '[data-testid="expandable-text-box"]',  # New LinkedIn structure (Jan 2026)
                '.jobs-description-content__text',
                '.jobs-description',
                '.show-more-less-html__markup',
                '#job-details',
                '[class*="jobs-description"]',
            ]

            for selector in selectors:
                # Get ALL matching elements and find the longest text (the job description)
                elems = page.query_selector_all(selector)
                best_text = ""
                for elem in elems:
                    text = elem.inner_text().strip()
                    if len(text) > len(best_text):
                        best_text = text
                if len(best_text) > 100:  # Needs meaningful content, not just a label
                    return best_text[:5000]

            # Last resort: find any element with substantial text containing job keywords
            desc_container = page.query_selector('[class*="description"]')
            if desc_container:
                text = desc_container.inner_text().strip()
                if len(text) > 100:
                    return text[:5000]

            # Debug: log what we can see
            custom_print("DEBUG", f"Page URL: {page.url}")
            body_text = page.query_selector('body').inner_text()[:500] if page.query_selector('body') else "NO BODY"
            custom_print("DEBUG", f"Page preview: {body_text[:200]}...")

        except Exception as e:
            custom_print("ERROR", f"Could not extract description: {e}")

        # Return None if extraction failed - job should be skipped
        custom_print("ERROR", f"No job description found for {job.get('title', 'Unknown')} - will skip")
        return None

    async def batch_prefilter_async(self, jobs: List[Dict], db=None) -> List[Dict]:
        await self._ensure_initialized()

        if not self.config.USE_PREFILTER or len(jobs) == 0:
            return jobs

        custom_print("EVALUATING", f"Pre-filtering {len(jobs)} jobs for obvious bad matches...")

        batch_size = self.config.PREFILTER_BATCH_SIZE
        all_filtered_jobs = []

        for batch_start in range(0, len(jobs), batch_size):
            batch_jobs = jobs[batch_start:batch_start + batch_size]

            job_list = "\n".join([
                f"{idx}. \"{job['title']}\" at {job['company']}"
                for idx, job in enumerate(batch_jobs)
            ])

            prompt = f"""
I'm evaluating {len(batch_jobs)} LinkedIn jobs. Remove ONLY the OBVIOUS false flags that are clearly unrelated to my background.

**IMPORTANT: Be VERY PERMISSIVE - only flag jobs that are unmistakably wrong.**
- ✅ KEEP: Anything remotely related to software, tech, AI, ML, engineering, leadership, architecture
- ✅ KEEP: All engineering levels (Senior, Staff, Principal, Lead) - evaluate fit individually later
- ✅ KEEP: Roles where technical skills match, regardless of seniority level stated
- ❌ REMOVE ONLY: Dentist, construction, sales, marketing, finance, non-tech roles

**My Background:**
{CV_FULL_TEXT}

**Jobs to pre-filter:**
{job_list}

Return JSON array of indices to KEEP (not remove). When in doubt, KEEP the job.
{{"keep_indices": [0, 1, 3, 5, ...]}}
"""

            try:
                result = await self.ai_service.call_gemini_structured(
                    prompt=prompt,
                    response_schema=PreFilterResult,
                    model=self.config.GEMINI_MODEL_EVAL,
                    temperature=self.config.GEMINI_TEMPERATURE
                )

                keep_indices = set(result['keep_indices'])

                batch_filtered = []
                for idx, job in enumerate(batch_jobs):
                    if idx in keep_indices:
                        batch_filtered.append(job)
                    else:
                        custom_print("DEBUG", f"Pre-filter removed: {job['title']} at {job['company']}")

                        # Fix: Immediately record rejection in DB to prevent infinite loops
                        if db:
                            db.insert_evaluation(
                                job_id=job['id'],
                                evaluation={
                                    "apply": False,
                                    "confidence": 0,
                                    "reason": "Auto-rejected by Pre-filter (Irrelevant)"
                                }
                            )

                all_filtered_jobs.extend(batch_filtered)

            except Exception as e:
                custom_print("WARNING", f"Pre-filter error: {e} - keeping all jobs in this batch")
                all_filtered_jobs.extend(batch_jobs)

        removed_count = len(jobs) - len(all_filtered_jobs)
        if removed_count > 0:
            custom_print("SUCCESS",
                         f"Pre-filter removed {removed_count} obvious bad matches ({len(all_filtered_jobs)} remaining)")
        else:
            custom_print("INFO", f"Pre-filter kept all {len(jobs)} jobs (no obvious bad matches)")

        return all_filtered_jobs

    async def evaluate_job_async(self, job: Dict, description: str = None) -> Dict:
        await self._ensure_initialized()

        # Description is required - jobs without descriptions are skipped before this point
        if description is None:
            raise ValueError(f"Job description is required for evaluation: {job.get('title', 'Unknown')}")

        prompt = f"""
Evaluate if this job matches my profile and career goals:

**Job Title:** {job['title']}
**Company:** {job['company']}

**Job Description:**
{description}

**My Profile:**
{CV_FULL_TEXT}

**Instructions:**
- Carefully read the job requirements and compare to my skills and experience.
- **Skills Match:** Does my technical background (Python, AI/ML, React, FastAPI, VR, architecture experience) align with what they need?
- **Experience Level:** Consider my 10+ years including CTO/leadership experience. Does the role scope make sense for someone with this background? (Note: I'm open to strong opportunities at various levels - don't auto-reject based on title alone)
- **Salary Logic:** Evaluate if the role likely provides fair compensation for the level and location.
  - **Do NOT reject** the job just because salary is not listed.
  - Consider role scope and responsibilities, not just title.
- **Deal Breakers:** Reject only if there's a fundamental mismatch:
  - Requires deep expertise in tech stacks I don't have (e.g., requires Java/C# expert when I'm Python-focused)
  - Role scope doesn't utilize my experience (e.g., junior-level responsibilities)
  - Clear red flags in job description (unrealistic expectations, toxic culture indicators)
- **Confidence:** 0-100 (higher = better match). Consider both skills alignment AND career trajectory fit.

Respond with JSON only (no markdown, no backticks):
{{"apply": true/false, "confidence": 0-100, "reason": "brief explanation"}}
"""

        try:
            result = await self.ai_service.call_gemini_structured(
                prompt=prompt,
                response_schema=JobEvaluation,
                model=self.config.GEMINI_MODEL_EVAL,
                temperature=self.config.GEMINI_TEMPERATURE
            )
            return result
        except Exception as e:
            custom_print("ERROR", f"Gemini error: {e}")
            return {"apply": False, "confidence": 0, "reason": f"API error: {str(e)}"}

    def filter_jobs_sync(self, jobs: List[Dict], threshold: int = None, page=None, db=None) -> List[Dict]:
        if threshold is None:
            threshold = self.config.CONFIDENCE_THRESHOLD

        if self.config.USE_PREFILTER:
            # Pass db here so prefilter can save rejections
            jobs = asyncio.run(self.batch_prefilter_async(jobs, db=db))

            if len(jobs) == 0:
                custom_print("WARNING", "Pre-filter removed all jobs - try adjusting search keywords")
                return []

        good_jobs = []

        custom_print("EVALUATING", f"Detailed evaluation of {len(jobs)} jobs")
        if page:
            custom_print("EVALUATING", "Reading job descriptions for accurate matching")

        import time
        for idx, job in enumerate(jobs):
            keyword = job.get('search_keyword', '')
            location = job.get('search_location', '')

            print(f"\n[{idx + 1}/{len(jobs)}] {job['title']}")
            if keyword and location:
                print(f"Company: {job['company']} | Search: '{keyword}' in {location}")
            else:
                print(f"Company: {job['company']}")

            if idx > 0:
                time.sleep(2)

            description = None
            if page:
                description = self._extract_job_description(job, page)

                # Skip job if no description found - BUT save evaluation to prevent infinite loop
                if description is None:
                    custom_print("ERROR", f"Skipping '{job['title']}' - no description available")
                    # Save a "skipped" evaluation so job doesn't keep reappearing
                    skip_evaluation = {
                        'apply': False,
                        'confidence': 0,
                        'reason': 'No job description available - could not evaluate'
                    }
                    job['evaluation'] = skip_evaluation
                    if db and 'id' in job:
                        db.insert_evaluation(job['id'], skip_evaluation)
                    continue

                job['description'] = description

                if db and 'id' in job:
                    db.update_job_description(job['id'], description)
                    custom_print("DEBUG", "Saved job description to database")

            evaluation = asyncio.run(self.evaluate_job_async(job, description=description))
            job['evaluation'] = evaluation

            if db and 'id' in job:
                db.insert_evaluation(job['id'], evaluation)

            confidence = evaluation.get('confidence', 0)
            reason = evaluation.get('reason', 'No reason provided')
            should_apply = evaluation.get('apply', False)

            if should_apply and confidence >= threshold:
                good_jobs.append(job)
                custom_print("MATCH", f"✓ APPLY ({confidence}%): {reason}")
            else:
                custom_print("SKIP", f"✗ SKIP ({confidence}%): {reason}")

        custom_print("SUCCESS", f"{len(good_jobs)} good matches out of {len(jobs)} jobs (Threshold: {threshold}%)")
        return good_jobs