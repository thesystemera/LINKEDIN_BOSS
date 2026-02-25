import time
import random
import asyncio
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Coroutine
from playwright.sync_api import Page

from src.services.form_field_filler import FormFieldFiller
from src.utils.logger import custom_print
from src.config import settings

class AutoApplier:
    def __init__(self, config):
        self.config = config
        self.form_filler = FormFieldFiller()
        self.debug_html_dir = settings.DATA_DIR / "debug_html"
        self.debug_html_dir.mkdir(parents=True, exist_ok=True)

    def _save_debug_html(self, page: Page, job: Dict, error_context: str):
        """Save modal HTML for debugging when validation errors occur."""
        try:
            modal = page.query_selector('[role="dialog"]')
            if not modal:
                return None

            html_content = modal.inner_html()

            # Create filename with timestamp and job info
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            job_id = job.get('url', '').split('/')[-2] if job.get('url') else 'unknown'
            company = re.sub(r'[^\w\-]', '_', job.get('company', 'unknown'))[:30]
            filename = f"{timestamp}_{company}_{job_id}.html"

            filepath = self.debug_html_dir / filename

            # Add context header
            header = f"""<!--
DEBUG HTML CAPTURE
==================
Timestamp: {datetime.now().isoformat()}
Job: {job.get('title', 'Unknown')}
Company: {job.get('company', 'Unknown')}
URL: {job.get('url', 'Unknown')}
Error Context: {error_context}
-->

"""
            filepath.write_text(header + html_content, encoding='utf-8')
            custom_print("DEBUG", f"Saved form HTML to: {filepath.name}")
            return filepath

        except Exception as e:
            custom_print("WARNING", f"Failed to save debug HTML: {e}")
            return None

    def _run_async(self, coro: Coroutine) -> Any:
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        return loop.run_until_complete(coro)

    def apply_to_job(self, page: Page, job: Dict) -> Dict:
        try:
            custom_print("APPLYING", f"Navigating to: {job['url']}")
            page.goto(job['url'], wait_until='domcontentloaded')

            time.sleep(2)

            current_url = page.url
            custom_print("DEBUG", f"Current URL: {current_url[:100]}")

            if 'authwall' in current_url or 'login' in current_url:
                custom_print("ERROR", "LinkedIn redirected to login/authwall - session may have expired")
                return {"status": "error", "error": "Session expired - need to re-login", "steps": 0}

            if 'search' in current_url or 'jobs/collections' in current_url:
                custom_print("WARNING", "LinkedIn redirected to search/collections page - likely already applied or job closed")
                return {"status": "skipped", "error": "Already applied or job unavailable", "steps": 0}

            new_pages = []
            def handle_popup(popup):
                custom_print("WARNING", f"Popup detected (closing): {popup.url[:60]}...")
                new_pages.append(popup)
                try:
                    popup.close()
                except:
                    pass

            page.context.on("page", handle_popup)

            read_time = random.uniform(
                self.config.JOB_READ_TIME_MIN,
                self.config.JOB_READ_TIME_MAX
            )
            custom_print("APPLYING", f"Reading job for {read_time:.1f} seconds...")
            time.sleep(read_time)

            custom_print("DEBUG", "Looking for Easy Apply button...")
            custom_print("DEBUG", f"Selector: {self.config.SELECTORS['easy_apply_button']}")

            try:
                custom_print("DEBUG", "Looking for Easy Apply button (checking for visible instance)")

                button_found = None

                time.sleep(1)

                # Try multiple selectors - LinkedIn changed from button to <a> tag (Jan 2026)
                easy_apply_selectors = [
                    '[data-view-name="job-apply-button"]',  # New LinkedIn structure (Jan 2026)
                    '[aria-label*="Easy Apply"]',
                    '.jobs-apply-button',
                ]

                for selector in easy_apply_selectors:
                    all_apply_buttons = page.query_selector_all(selector)
                    custom_print("DEBUG", f"Found {len(all_apply_buttons)} elements with '{selector}'")

                    for idx, btn in enumerate(all_apply_buttons):
                        if btn.is_visible():
                            button_found = btn
                            custom_print("SUCCESS", f"Found visible Easy Apply element (selector: {selector}, index {idx})")
                            break
                        else:
                            custom_print("DEBUG", f"  Element {idx} is hidden, skipping")

                    if button_found:
                        break

                if not button_found:
                    page.context.remove_listener("page", handle_popup)
                    all_buttons = page.query_selector_all('button')
                    custom_print("DEBUG", f"Found {len(all_buttons)} buttons total on page")
                    custom_print("DEBUG", "Showing first 20 buttons (visible status, text, class, aria-label):")
                    for idx, btn in enumerate(all_buttons[:20]):
                        try:
                            is_vis = "VIS" if btn.is_visible() else "HID"
                            text = btn.inner_text().strip()[:40] if btn.is_visible() else "[hidden]"
                            classes = btn.get_attribute('class') or ''
                            aria = btn.get_attribute('aria-label') or ''
                            btn_id = btn.get_attribute('id') or ''
                            custom_print("DEBUG", f"  [{is_vis}] Button {idx}: '{text}' | class='{classes[:40]}' | aria='{aria[:40]}' | id='{btn_id}'")
                        except:
                            custom_print("DEBUG", f"  [ERR] Button {idx}: Error reading properties")

                    return {"status": "no_easy_apply", "error": "Easy Apply button not found after trying all selectors", "steps": 0}

                custom_print("APPLYING", "Clicking Easy Apply button...")
                button_found.scroll_into_view_if_needed()
                time.sleep(0.5)
                button_found.click()

                time.sleep(1.0)

                if new_pages:
                    custom_print("WARNING", "Job opened a new window (likely external apply). Skipped to keep session clean.")
                    page.context.remove_listener("page", handle_popup)
                    return {"status": "manual_review_needed", "error": "Job opened external window/popup", "steps": 0}

            except Exception as e:
                custom_print("ERROR", f"Exception while looking for button: {str(e)}")
                page.context.remove_listener("page", handle_popup)
                return {"status": "no_easy_apply", "error": f"Easy Apply button error: {str(e)}", "steps": 0}

            page.context.remove_listener("page", handle_popup)

            try:
                page.wait_for_selector('[role="dialog"]', timeout=10000)
                time.sleep(1)
            except Exception as e:
                return {"status": "error", "error": f"Easy Apply modal didn't load: {str(e)}", "steps": 0}

            steps = 0
            max_steps = 25

            max_retries_per_page = 2
            current_page_retries = 0
            last_page_signature = None

            # Validation retry tracking
            validation_retry_count = 0
            last_filled_fields = None
            last_filled_answers = None

            # Q&A tracking for summary
            all_qa_pairs = []

            while steps < max_steps:
                steps += 1
                time.sleep(random.uniform(1, 2))

                custom_print("APPLYING", f"Step {steps}: Analyzing form...")
                fields = self.form_filler.detect_form_fields(page)

                current_signature = f"{len(fields)} fields"
                if fields:
                    field_ids = [f"{f.get('label','')}::{f.get('type','')}" for f in fields]
                    current_signature += " | " + " | ".join(sorted(field_ids))

                if current_signature == last_page_signature:
                    current_page_retries += 1
                    custom_print("WARNING", f"Stuck on same page (Retry {current_page_retries}/{max_retries_per_page})")

                    if current_page_retries > max_retries_per_page:
                        self._close_modal(page)
                        return {"status": "manual_review_needed", "error": "Stuck on same page (validation error?)", "steps": steps}
                else:
                    current_page_retries = 0
                    last_page_signature = current_signature

                if fields:
                    custom_print("APPLYING", f"Found {len(fields)} form fields, generating answers...")

                    has_file_upload = any(f['type'] == 'file' for f in fields)
                    if has_file_upload:
                        self._close_modal(page)
                        return {"status": "manual_review_needed", "error": "File upload required", "steps": steps}

                    try:
                        result = self._run_async(
                            self.form_filler.generate_field_answers(
                                fields,
                                job['title'],
                                job['company'],
                                job.get('description', 'No Description Available')
                            )
                        )

                        custom_print("APPLYING", f"Filling {len(result['answers'])} fields...")

                        self.form_filler.fill_fields(page, fields, result['answers'])

                        # Re-detect fields after filling - dropdowns may reveal conditional fields
                        time.sleep(1)
                        new_fields = self.form_filler.detect_form_fields(page)
                        if len(new_fields) > len(fields):
                            # Find fields that appeared after filling (conditional fields)
                            old_labels = {f.get('label', '') for f in fields}
                            conditional = [f for f in new_fields if f.get('label', '') not in old_labels]
                            if conditional:
                                custom_print("FORM", f"Found {len(conditional)} conditional fields after dropdown selection")
                                conditional_result = self._run_async(
                                    self.form_filler.generate_field_answers(
                                        conditional,
                                        job['title'],
                                        job['company'],
                                        job.get('description', 'No Description Available')
                                    )
                                )
                                self.form_filler.fill_fields(page, conditional, conditional_result['answers'])

                        # Store Q&A for summary
                        for idx, field in enumerate(fields):
                            if idx in result['answers']:
                                answer = result['answers'][idx]
                                all_qa_pairs.append({
                                    "question": field.get('label', 'Unknown'),
                                    "answer": str(answer)[:200]  # Truncate long answers
                                })

                        # Store for potential retry
                        last_filled_fields = fields
                        last_filled_answers = result['answers']
                        validation_retry_count = 0  # Reset retry count for new page

                        time.sleep(random.uniform(0.5, 1.0))

                    except Exception as e:
                        custom_print("ERROR", f"Form filling failed: {e}")
                        self._close_modal(page)
                        return {"status": "manual_review_needed", "error": f"Form filling error: {str(e)}", "steps": steps}

                submit_btn = page.query_selector(self.config.SELECTORS['submit_button'])
                if submit_btn:
                    try:
                        follow_regex = re.compile(r"Follow.*?to stay up to date", re.IGNORECASE)
                        follow_box = page.get_by_label(follow_regex).first

                        if follow_box.count() > 0 and follow_box.is_visible():
                            if follow_box.is_checked():
                                custom_print("APPLYING", "Unchecking 'Follow Company' checkbox...")
                                follow_box.evaluate('''(el) => {
                                    el.click();
                                    if (el.checked) {
                                        el.checked = false;
                                        el.dispatchEvent(new Event('change', { bubbles: true }));
                                        el.dispatchEvent(new Event('input', { bubbles: true }));
                                    }
                                }''')
                                time.sleep(0.5)
                    except Exception as e:
                        custom_print("DEBUG", f"Follow box check skipped: {e}")

                    # Print Q&A Summary before submission
                    if all_qa_pairs:
                        custom_print("SUMMARY", "=" * 60)
                        custom_print("SUMMARY", "APPLICATION FORM SUMMARY")
                        custom_print("SUMMARY", "=" * 60)
                        for idx, qa in enumerate(all_qa_pairs, 1):
                            custom_print("SUMMARY", f"Q{idx}: {qa['question']}")
                            custom_print("SUMMARY", f"A{idx}: {qa['answer']}")
                            if idx < len(all_qa_pairs):
                                custom_print("SUMMARY", "-" * 40)
                        custom_print("SUMMARY", "=" * 60)

                    if self.config.MANUAL_APPROVAL:
                        custom_print("APPLYING", "=" * 60)
                        custom_print("APPLYING", "READY TO SUBMIT APPLICATION")
                        custom_print("APPLYING", "=" * 60)
                        custom_print("INFO", f"Job: {job['title']}")
                        custom_print("INFO", f"Company: {job['company']}")
                        custom_print("APPLYING", "=" * 60)

                        if self.config.DRY_RUN:
                            custom_print("WARNING", "[DRY RUN MODE] Would submit here, but stopping.")
                            self._close_modal(page)
                            return {"status": "dry_run", "error": None, "steps": steps}

                        response = input("\nSubmit this application? (y/n/v for view form): ").lower().strip()

                        if response == 'v':
                            custom_print("WARNING", "Take a moment to review the filled form in the browser window.")
                            response = input("Submit? (y/n): ").lower().strip()

                        if response != 'y':
                            custom_print("WARNING", "Skipped by user")
                            self._close_modal(page)
                            return {"status": "skipped_by_user", "error": "User declined", "steps": steps}

                    custom_print("APPLYING", f"Submitting application (step {steps})...")
                    submit_btn.click()
                    time.sleep(3)

                    if self._check_success(page):
                        return {"status": "success", "error": None, "steps": steps}
                    else:
                        return {"status": "error", "error": "Submit failed", "steps": steps}

                review_btn = page.query_selector(self.config.SELECTORS['review_button'])
                if review_btn:
                    custom_print("APPLYING", "Review step...")
                    review_btn.click()
                    time.sleep(2)

                    error_messages = page.query_selector_all('[role="alert"], .artdeco-inline-feedback--error, [id*="error"]')
                    if error_messages:
                        visible_errors = [err for err in error_messages if err.is_visible()]
                        if visible_errors:
                            # Extract error texts
                            error_texts = []
                            custom_print("ERROR", f"Form validation failed! Found {len(visible_errors)} error(s):")
                            for idx, err in enumerate(visible_errors[:5]):
                                try:
                                    err_text = err.inner_text().strip()
                                    if err_text and len(err_text) > 0:
                                        custom_print("ERROR", f"  {idx+1}. {err_text[:100]}")
                                        error_texts.append(err_text)
                                except:
                                    pass

                            # Save HTML for debugging
                            self._save_debug_html(page, job, f"Review validation failed: {'; '.join(error_texts[:3])}")

                            # Try to fix with AI if retry enabled and not exceeded
                            if (self.config.ENABLE_VALIDATION_RETRY and
                                validation_retry_count < self.config.MAX_VALIDATION_RETRIES and
                                last_filled_fields and last_filled_answers):

                                validation_retry_count += 1
                                custom_print("WARNING", f"Attempting AI fix (retry {validation_retry_count}/{self.config.MAX_VALIDATION_RETRIES})...")

                                try:
                                    # Call AI to fix validation errors
                                    fixed_answers = self._run_async(
                                        self.form_filler.fix_validation_errors(
                                            fields=last_filled_fields,
                                            current_answers=last_filled_answers,
                                            error_messages=error_texts
                                        )
                                    )

                                    custom_print("FORM", f"Re-filling form with corrected answers...")
                                    self.form_filler.fill_fields(page, last_filled_fields, fixed_answers)
                                    last_filled_answers = fixed_answers  # Update for potential next retry
                                    time.sleep(1)

                                    # Click Review button again to re-validate
                                    review_btn.click()
                                    time.sleep(2)

                                    # Check if errors are gone
                                    error_check = page.query_selector_all('[role="alert"], .artdeco-inline-feedback--error')
                                    still_errors = [e for e in error_check if e.is_visible()]

                                    if not still_errors:
                                        custom_print("SUCCESS", "Validation errors fixed! Continuing...")
                                        continue  # Go to next step
                                    else:
                                        custom_print("WARNING", f"Still have {len(still_errors)} errors after retry")
                                        # Loop will continue and either retry again or give up

                                except Exception as fix_error:
                                    custom_print("ERROR", f"Fix attempt failed: {fix_error}")
                                    # Fall through to give up

                            # Give up if retry disabled, exceeded, or no fields to retry
                            if validation_retry_count >= self.config.MAX_VALIDATION_RETRIES:
                                custom_print("WARNING", f"Needs manual review: Form validation failed with {len(visible_errors)} errors (retries exhausted)")
                            self._close_modal(page)
                            return {"status": "manual_review_needed", "error": f"Form validation failed with {len(visible_errors)} errors after {validation_retry_count} retries", "steps": steps}

                    continue

                next_btn = page.query_selector(self.config.SELECTORS['next_button'])
                if next_btn:
                    time.sleep(1.5)

                    is_disabled = next_btn.get_attribute('disabled')
                    is_aria_disabled = next_btn.get_attribute('aria-disabled')

                    if is_disabled or is_aria_disabled == 'true':
                        custom_print("ERROR", "Next button is disabled - form validation failed!")
                        error_messages = page.query_selector_all('[role="alert"], .artdeco-inline-feedback--error, [id*="error"]')
                        visible_errors = [err for err in error_messages if err.is_visible()]
                        error_texts = []
                        if visible_errors:
                            custom_print("ERROR", f"Found {len(visible_errors)} validation error(s):")
                            for idx, err in enumerate(visible_errors[:5]):
                                try:
                                    err_text = err.inner_text().strip()
                                    if err_text:
                                        custom_print("ERROR", f"  {idx+1}. {err_text[:100]}")
                                        error_texts.append(err_text)
                                except:
                                    pass
                        # Save HTML for debugging
                        self._save_debug_html(page, job, f"Next button disabled: {'; '.join(error_texts[:3])}")
                        self._close_modal(page)
                        return {"status": "manual_review_needed", "error": "Form validation failed (Next button disabled)", "steps": steps}

                    custom_print("APPLYING", "Next step...")
                    next_btn.click()
                    time.sleep(2)

                    # Check for validation errors after Next click (same as Review)
                    error_messages = page.query_selector_all('[role="alert"], .artdeco-inline-feedback--error, [id*="error"]')
                    visible_errors = [err for err in error_messages if err.is_visible()]
                    if visible_errors:
                        custom_print("ERROR", f"Validation errors after Next click ({len(visible_errors)}):")
                        error_texts = []
                        for idx, err in enumerate(visible_errors[:5]):
                            try:
                                err_text = err.inner_text().strip()
                                # Walk up DOM to find the parent field's label
                                field_label = err.evaluate('''el => {
                                    let parent = el;
                                    for (let i = 0; i < 8; i++) {
                                        parent = parent.parentElement;
                                        if (!parent) break;
                                        // Check for label, legend, or title span
                                        const label = parent.querySelector('label, legend, [data-test-form-builder-radio-button-form-component__title], span[aria-hidden="true"]');
                                        if (label) {
                                            const text = label.textContent.trim();
                                            if (text && text.length > 3 && text.length < 200) return text;
                                        }
                                        // Check for a nearby header/label sibling
                                        const prev = parent.previousElementSibling;
                                        if (prev) {
                                            const prevText = prev.textContent.trim();
                                            if (prevText && prevText.length > 3 && prevText.length < 200) return prevText;
                                        }
                                    }
                                    // Last resort: get parent class names for identification
                                    return parent ? parent.className.substring(0, 100) : "unknown";
                                }''')
                                if err_text:
                                    custom_print("ERROR", f"  {idx+1}. [{field_label}] {err_text[:150]}")
                                    error_texts.append(f"{field_label}: {err_text}")
                            except:
                                pass
                        # Save HTML for debugging
                        self._save_debug_html(page, job, f"Next click errors: {'; '.join(error_texts[:3])}")

                    continue

                custom_print("WARNING", f"No action found at step {steps}")

                generic_buttons = page.query_selector_all('button')
                progressed = False
                for btn in generic_buttons:
                    text = btn.inner_text().lower()
                    if any(keyword in text for keyword in ['continue', 'next', 'submit', 'review']):
                        custom_print("APPLYING", f"Trying button: {text}")
                        btn.click()
                        time.sleep(1)
                        progressed = True
                        break

                if not progressed:
                    self._close_modal(page)
                    return {"status": "manual_review_needed", "error": "Complex form - couldn't progress", "steps": steps}

            self._close_modal(page)
            return {"status": "error", "error": "Max steps exceeded", "steps": steps}

        except Exception as e:
            try:
                page.context.remove_listener("page", handle_popup)
            except:
                pass
            self._close_modal(page)
            return {"status": "error", "error": str(e), "steps": 0}

    def _check_success(self, page: Page) -> bool:
        success_texts = [
            "Application sent",
            "Application submitted",
            "Your application was sent",
            "successfully sent"
        ]

        for text in success_texts:
            if page.query_selector(f'text=/{text}/i'):
                return True

        time.sleep(2)
        modal = page.query_selector('[role="dialog"]')
        return modal is None

    def _close_modal(self, page: Page):
        try:
            close_btn = page.query_selector(self.config.SELECTORS['close_button'])
            if close_btn:
                close_btn.click()
                time.sleep(1)

                discard_btn = page.query_selector('button:has-text("Discard")')
                if discard_btn:
                    discard_btn.click()
                    time.sleep(1)
        except Exception:
            pass