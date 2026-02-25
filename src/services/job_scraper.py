import time
import re
from typing import List, Dict
from playwright.sync_api import Page

from src.utils.logger import custom_print

class JobScraper:
    def __init__(self, config):
        self.config = config

    def scrape_recommended_jobs(self, page: Page, max_jobs: int = 100) -> List[Dict]:
        custom_print("SCRAPING", "=" * 60)
        custom_print("SCRAPING", "SCRAPING LINKEDIN JOBS")
        custom_print("SCRAPING", "=" * 60)

        all_jobs = []
        seen_urls = set()

        if self.config.USE_SEARCH_MODE:
            locations = self.config.SEARCH_LOCATIONS
            keywords = self.config.SEARCH_KEYWORDS or [""]

            total_searches = len(keywords) * len(locations)

            custom_print("SCRAPING", "Using SEARCH mode with filters:")
            custom_print("INFO", f"Locations: {', '.join(locations)}")
            custom_print("INFO", f"Keywords: {keywords if self.config.SEARCH_KEYWORDS else 'None (uses LinkedIn profile)'}")
            custom_print("INFO", "Date filter: Past week")
            custom_print("INFO", "Easy Apply: YES")
            custom_print("SCRAPING", f"Will perform {total_searches} search(es) ({len(keywords)} keyword(s) x {len(locations)} location(s))")

            current_search = 0
            consecutive_failures = 0
            browser_dead = False

            for keyword in keywords:
                if browser_dead:
                    break

                for location in locations:
                    if browser_dead:
                        break

                    current_search += 1
                    custom_print("SCRAPING", f"Search {current_search}/{total_searches}: '{keyword}' in {location}")

                    search_url = self.config.build_search_url(location, keyword)
                    custom_print("SCRAPING", f"Navigating to: {search_url}")

                    try:
                        page.goto(search_url, wait_until='domcontentloaded')
                        time.sleep(3)

                        jobs = self._extract_jobs_from_page(page, seen_urls, keyword, location)
                        all_jobs.extend(jobs)
                        consecutive_failures = 0  # Reset on success

                        custom_print("INFO", f"Total so far: {len(all_jobs)} jobs")

                        if len(all_jobs) >= max_jobs:
                            break

                    except Exception as e:
                        error_str = str(e).lower()
                        consecutive_failures += 1

                        # Detect browser/context closed (bot detection or session killed)
                        if 'closed' in error_str or 'target page' in error_str or 'context' in error_str:
                            custom_print("ERROR", "=" * 60)
                            custom_print("ERROR", "BROWSER SESSION TERMINATED")
                            custom_print("ERROR", "LinkedIn may have detected automation or rate limited.")
                            custom_print("ERROR", f"Completed {current_search - 1}/{total_searches} searches before termination.")
                            custom_print("ERROR", f"Scraped {len(all_jobs)} jobs before session ended.")
                            custom_print("ERROR", "=" * 60)
                            browser_dead = True
                            break

                        # Detect too many consecutive failures
                        if consecutive_failures >= 3:
                            custom_print("ERROR", "=" * 60)
                            custom_print("ERROR", f"TOO MANY CONSECUTIVE FAILURES ({consecutive_failures})")
                            custom_print("ERROR", "Stopping scraper - possible rate limiting or connection issue.")
                            custom_print("ERROR", f"Scraped {len(all_jobs)} jobs before stopping.")
                            custom_print("ERROR", "=" * 60)
                            browser_dead = True
                            break

                        custom_print("ERROR", f"Search failed: {e}")

                if len(all_jobs) >= max_jobs:
                    break
        else:
            page.goto("https://www.linkedin.com/jobs/collections/recommended/", wait_until='domcontentloaded')
            time.sleep(3)
            all_jobs = self._extract_jobs_from_page(page, seen_urls)

        unique_jobs = []
        seen_ids = set()
        for job in all_jobs:
            unique_key = job.get('linkedin_job_id') or job['url']
            if unique_key not in seen_ids:
                unique_jobs.append(job)
                seen_ids.add(unique_key)

        custom_print("SCRAPING", "=" * 60)
        custom_print("SUCCESS", f"Scraped {len(unique_jobs)} Easy Apply jobs (deduplicated)")
        custom_print("SCRAPING", "=" * 60)

        return unique_jobs[:max_jobs]

    def _extract_id_from_url(self, url: str) -> str:
        match = re.search(r"view/(\d+)", url)
        if match:
            return match.group(1)
        return None

    def _extract_jobs_from_page(self, page: Page, seen_urls: set, keyword: str = "", location: str = "") -> List[Dict]:
        jobs = []

        for i in range(1, 5):
            page.evaluate(f"window.scrollTo(0, document.body.scrollHeight * {i/5});")
            time.sleep(self.config.SCROLL_PAUSE_TIME)

            try:
                see_more = page.query_selector('button[aria-label="See more jobs"]')
                if see_more and see_more.is_visible():
                    see_more.click()
                    time.sleep(2)
            except:
                pass

        job_card_selector = '.job-card-container, .jobs-search-results__list-item'

        job_cards = page.query_selector_all(job_card_selector)

        if not job_cards:
            custom_print("WARNING", "No jobs found!")
            return []

        custom_print("SUCCESS", f"Found {len(job_cards)} job cards (Easy Apply filtered by f_AL=true)")

        for idx, card in enumerate(job_cards):
            try:
                link_elem = card.query_selector('a.job-card-list__title--link') or card.query_selector('a.job-card-container__link')

                title_elem = link_elem if link_elem else card.query_selector('.artdeco-entity-lockup__title')

                company_elem = card.query_selector('.job-card-container__primary-description, .artdeco-entity-lockup__subtitle')

                if not (title_elem and company_elem and link_elem):
                    custom_print("WARNING", f"Card {idx}: Missing elements - link={link_elem is not None}, title={title_elem is not None}, company={company_elem is not None}")
                    continue

                # Check if already applied - skip to avoid wasting Gemini API calls
                card_text = card.inner_text()
                if "Application submitted" in card_text:
                    title_text = title_elem.inner_text().strip()
                    custom_print("INFO", f"Card {idx}: Already applied - skipping '{title_text[:50]}'")
                    continue

                url = link_elem.get_attribute('href')

                if url:
                    if not url.startswith('http'):
                        url = f"https://www.linkedin.com{url}"

                    url = url.split('?')[0]

                if not url:
                    custom_print("WARNING", f"Card {idx}: No URL found (link element has no href attribute)")
                    continue

                # Skip LinkedIn Premium recommendation/collection cards (not actual job listings)
                if '/jobs/collections/' in url or url.endswith('/jobs/search/'):
                    continue

                job_id_str = self._extract_id_from_url(url)

                if not job_id_str:
                    custom_print("WARNING", f"Card {idx}: Could not extract ID from {url}")
                    continue

                if job_id_str in seen_urls:
                    continue

                seen_urls.add(job_id_str)

                job = {
                    "linkedin_job_id": job_id_str,
                    "title": title_elem.inner_text().strip(),
                    "company": company_elem.inner_text().strip(),
                    "url": url,
                    "has_easy_apply": True,
                    "search_keyword": keyword,
                    "search_location": location
                }
                jobs.append(job)
                custom_print("SUCCESS", f"{len(jobs)}: {job['title']} (ID: {job_id_str})")

            except Exception as e:
                custom_print("ERROR", f"Card {idx}: Failed to extract job data - {str(e)}")
                continue

        if self.config.USE_SEARCH_MODE:
            try:
                current_page_elem = page.query_selector('.artdeco-pagination__indicator--active')
                if current_page_elem:
                    current_page = current_page_elem.inner_text().strip()
                    total_pages_elem = page.query_selector_all('.artdeco-pagination__indicator')
                    total_pages = total_pages_elem[-1].inner_text().strip() if total_pages_elem else "?"
                    custom_print("DEBUG", f"Pagination: Page {current_page} of {total_pages}")

                next_button = page.query_selector('button[aria-label="Next"], a[aria-label="Next"]')
                if next_button and next_button.is_enabled():
                    page_num_match = "start=" in page.url
                    if not page_num_match or "start=75" not in page.url: # Limit to ~4 pages
                        custom_print("DEBUG", f"Clicking Next button to preserve all filters")
                        current_url = page.url
                        next_button.click()
                        time.sleep(3)

                        # Verify URL changed (pagination worked)
                        if page.url != current_url:
                            custom_print("DEBUG", f"Next page: {page.url}")
                            next_page_jobs = self._extract_jobs_from_page(page, seen_urls, keyword, location)
                            jobs.extend(next_page_jobs)
                        else:
                            custom_print("DEBUG", "Pagination ended (URL didn't change)")
            except Exception as e:
                custom_print("DEBUG", f"Pagination error: {e}")

        return jobs