import re
import time
import random
from typing import Dict, List, Optional

from playwright.sync_api import Page

from src.services.browser import SessionExpired, linkedin_logged_in
from src.utils.logger import custom_print

CARDS_JS = """
() => {
  const clean = s => (s || '').replace(/\\s+/g, ' ').trim();
  const out = [];
  const seen = new Set();
  // whole card first: the nearest match (e.g. div.job-card-list__entity-lockup) leaves out the footer with Easy Apply / Applied / Promoted
  const CARD_SELECTORS = ['li[data-occludable-job-id]', '[data-view-name="job-card"]', '[data-job-id]', 'li.scaffold-layout__list-item', 'li.jobs-search-results__list-item', '.job-card-container'];
  const cardOf = a => { for (const s of CARD_SELECTORS) { const c = a.closest(s); if (c) return c; } return a.closest('div[class*="job-card"], li') || a.parentElement; };
  const push = (id, card, link) => {
    if (!id || seen.has(id)) return;
    seen.add(id);
    let lines = (card.innerText || '').split('\\n').map(clean).filter(Boolean);
    lines = lines.filter((l, i) => i === 0 || l !== lines[i - 1]);
    const titleEl = card.querySelector('.job-card-list__title--link strong, .job-card-list__title, [class*="job-card-list__title"], .artdeco-entity-lockup__title, a[href*="/jobs/view/"] strong') || link;
    let title = clean(titleEl ? (titleEl.innerText || '').split('\\n')[0] : '') || clean(link && link.getAttribute('aria-label')) || lines[0] || '';
    title = title.replace(/\\s+with verification$/i, '').replace(/\\(verified job\\)/ig, ' ').replace(/\\s+/g, ' ').trim();
    const h = Math.floor(title.length / 2);
    if (title.length > 3 && title.length % 2 === 0 && title.slice(0, h) === title.slice(h)) title = title.slice(0, h);
    const words = title.split(' '); const wh = Math.floor(words.length / 2);
    if (words.length > 1 && words.length % 2 === 0 && words.slice(0, wh).join(' ') === words.slice(wh).join(' ')) title = words.slice(0, wh).join(' ');
    const compEl = card.querySelector('.artdeco-entity-lockup__subtitle, .job-card-container__primary-description, [class*="company-name"], [class*="subtitle"]');
    let company = clean(compEl ? compEl.innerText.split('\\n')[0] : '');
    const locEl = card.querySelector('.job-card-container__metadata-wrapper li, .artdeco-entity-lockup__caption li, [class*="metadata"] li, .job-card-container__metadata-item, [class*="caption"]');
    let location = clean(locEl ? locEl.innerText.split('\\n')[0] : '');
    const ct = l => l.replace(/\\(verified job\\)/ig, ' ').replace(/\\s+with verification$/i, '').replace(/\\s+/g, ' ').trim();
    const rest = lines.filter(l => { const c = ct(l); return !(c === title || (c.includes(title) && c.length <= title.length * 2 + 2)) && !/with verification$/i.test(l); });
    if (!company) company = rest[0] || '';
    const notLoc = l => /^posted|\\bago\\b|applicant|promoted|viewed|easy apply|verified|actively|reviewing|alumni|connections?|school/i.test(l);
    if (!location || notLoc(location)) location = rest.find(l => /,|remote|hybrid|on-site|new zealand|australia/i.test(l) && l !== company && !notLoc(l)) || '';
    const text = lines.join(' | ');
    const salary = lines.find(l => /(\\$|NZ\\$|A\\$|US\\$|€|£)\\s?\\d|\\d\\s?(k|K)\\b.*\\/(yr|hr|day)|\\/(yr|hr|day)\\b|per (hour|annum|day)/.test(l) && /\\d/.test(l)) || '';
    out.push({
      id, title, company, location, salary,
      easy: /easy apply/i.test(text),
      applied: rest.some(l => /^Applied$|^Applied \\d+ (second|minute|hour|day|week|month)s? ago$|^Application submitted$|^Applied on \\d/.test(l)),
      promoted: /promoted/i.test(text),
      workplace: (location.match(/\\((remote|hybrid|on-site)\\)/i) || text.match(/\\b(remote|hybrid|on-site)\\b/i) || [,''])[1].toLowerCase()
    });
  };
  document.querySelectorAll('a[href*="/jobs/view/"], a[href*="currentJobId="]').forEach(a => {
    const href = a.getAttribute('href') || '';
    if (/\\/apply\\/|openSDUIApplyFlow/.test(href) || /^(easy )?apply$/i.test(clean(a.innerText))) return;
    if (a.closest('nav, header, footer, [data-view-name="job-detail-page"] [data-view-name="job-apply-button"]')) return;
    const m = href.match(/\\/jobs\\/view\\/(?:[^/?]*-)?(\\d{6,})/) || href.match(/currentJobId=(\\d{6,})/);
    if (m) push(m[1], cardOf(a), a);
  });
  document.querySelectorAll('[data-occludable-job-id], [data-job-id]').forEach(c => {
    const id = c.getAttribute('data-occludable-job-id') || c.getAttribute('data-job-id');
    if (id && /^\\d{6,}$/.test(id) && (c.innerText || '').trim()) push(id, c, c.querySelector('a'));
  });
  const total = (document.body.innerText.match(/([\\d,]+)\\+?\\s+results?/i) || [,''])[1];
  const none = /no matching jobs found|we couldn('|’)t find a match/i.test(document.body.innerText.slice(0, 4000));
  return { jobs: out, total, none };
}
"""

SCROLL_LIST_JS = """
(frac) => {
  const first = document.querySelector('li[data-occludable-job-id], [data-job-id], .job-card-container');
  let el = first ? first.parentElement : null;
  while (el && el !== document.body) {
    const cs = getComputedStyle(el);
    if ((cs.overflowY === 'auto' || cs.overflowY === 'scroll') && el.scrollHeight > el.clientHeight + 50) break;
    el = el.parentElement;
  }
  if (el && el !== document.body) { el.scrollTop = el.scrollHeight * frac; return 'list'; }
  window.scrollTo(0, document.body.scrollHeight * frac);
  return 'window';
}
"""


class JobScraper:
    def __init__(self, config, db=None):
        self.config = config
        self.db = db

    def _plan(self) -> List[tuple]:
        combos = []
        for lane, kw in self.config.all_keywords():
            for loc in self.config.SEARCH_LOCATIONS:
                combos.append((lane, kw, loc))
        if self.db:
            last = self.db.search_last_runs()
            combos.sort(key=lambda c: (last.get((c[1], c[2]), ""), random.random()))
        else:
            random.shuffle(combos)
        return combos[: self.config.MAX_SEARCHES_PER_RUN]

    def scrape_recommended_jobs(self, page: Page, max_jobs: int = 100) -> List[Dict]:
        custom_print("SCRAPING", "=" * 60)
        plan = self._plan()
        custom_print("SCRAPING", f"Running {len(plan)} searches (rotating through {len(self.config.all_keywords())} keywords x {len(self.config.SEARCH_LOCATIONS)} locations)")
        custom_print("INFO", f"Easy Apply only: {self.config.EASY_APPLY_ONLY} | Date: {self.config.SEARCH_DATE_FILTER} | Types: {self.config.JOB_TYPES}")
        all_jobs: List[Dict] = []
        seen = set()
        failures = 0
        for n, (lane, kw, loc) in enumerate(plan, 1):
            if len(all_jobs) >= max_jobs:
                break
            custom_print("SCRAPING", f"[{n}/{len(plan)}] '{kw}' in {loc} ({lane})")
            found = 0
            try:
                for pg in range(self.config.MAX_PAGES_PER_SEARCH):
                    url = self.config.build_search_url(loc, kw, start=pg * 25)
                    page.goto(url, wait_until="domcontentloaded")
                    time.sleep(random.uniform(2.5, 4.0))
                    if not linkedin_logged_in(page):
                        raise SessionExpired("LinkedIn session expired during search - run setup")
                    jobs = self._extract(page)
                    new = 0
                    for j in jobs:
                        if j["id"] in seen or j.get("applied"):
                            continue
                        seen.add(j["id"])
                        all_jobs.append({
                            "linkedin_job_id": j["id"],
                            "title": j["title"],
                            "company": j["company"],
                            "location": j["location"],
                            "salary_text": j["salary"],
                            "workplace": j["workplace"],
                            "apply_type": "easy" if j["easy"] else "unknown",
                            "url": f"https://www.linkedin.com/jobs/view/{j['id']}/",
                            "search_keyword": kw,
                            "search_location": loc,
                            "lane": lane,
                        })
                        new += 1
                    found += new
                    if len(jobs) < 20:
                        break
                    time.sleep(random.uniform(2, 5))
                failures = 0
                custom_print("INFO", f"  +{found} new (total {len(all_jobs)})")
                if self.db:
                    self.db.log_search(kw, loc, found)
            except SessionExpired:
                raise
            except Exception as e:
                failures += 1
                custom_print("ERROR", f"Search failed: {str(e)[:150]}")
                if "closed" in str(e).lower() or failures >= 3:
                    custom_print("ERROR", "Stopping scraper - browser closed or repeated failures (possible rate limiting)")
                    break
            time.sleep(random.uniform(3, 8))
        custom_print("SUCCESS", f"Scraped {len(all_jobs)} jobs")
        return all_jobs[:max_jobs]

    def _extract(self, page: Page) -> List[Dict]:
        for frac in (0.25, 0.5, 0.75, 1.0, 1.0):
            try:
                page.evaluate(SCROLL_LIST_JS, frac)
            except Exception:
                pass
            time.sleep(random.uniform(0.8, 1.6) + self.config.SCROLL_PAUSE_TIME / 4)
        r = page.evaluate(CARDS_JS)
        if r.get("none"):
            return []
        if not r["jobs"]:
            custom_print("WARNING", "No job cards detected on results page (LinkedIn markup may have changed - run: python src/main.py capture)")
        bad = [j for j in r["jobs"] if not j["title"] or not j["company"]]
        if bad:
            custom_print("WARNING", f"{len(bad)} cards missing title/company")
        return [j for j in r["jobs"] if j["title"]]

    def _extract_id_from_url(self, url: str) -> Optional[str]:
        m = re.search(r"/jobs/view/(?:[^/?]*-)?(\d{6,})", url or "")
        return m.group(1) if m else None
