import time
import json
import re
from typing import Dict, List, Any
from pydantic import BaseModel, ConfigDict
from playwright.sync_api import Page

from src.config import settings
from src.services.ai_service import AIService
from src.services.cv_data import CV_SUPPLEMENTARY, CV_FULL_TEXT
from src.utils.logger import custom_print

FIELD_RULES = """
**INSTRUCTIONS:**

1. **USE CV_SUPPLEMENTARY AS YOUR SOURCE OF TRUTH:**
   - All experience timelines, tech proficiency, and context are in the candidate data
   - Read it carefully and answer based on what's explicitly documented

2. **FOR "YEARS OF EXPERIENCE" QUESTIONS:**
   - Check CV_SUPPLEMENTARY['technology_experience_years'] FIRST
   - If not listed there, check CV_SUPPLEMENTARY['background_context'] for early/personal experience
   - Be honest - if you don't see clear work experience, answer conservatively (0-2)
   - Personal/hobby use ≠ professional work experience (unless question asks for "familiarity")

3. **NUMERIC_ONLY Fields:**
   - Return ONLY whole number digits (e.g., "5", "180000"). NO text, NO symbols, NO units, NO decimals.
   - For "years of experience" questions: ALWAYS round to nearest whole number (0.5 years → 1 year, 1.7 years → 2 years).

4. **BE SMART ABOUT AMBIGUOUS QUESTIONS:**
   - "Experience with Windows/Linux" usually means "used as development environment"
   - "Experience with Operating Systems" usually means "general OS knowledge" not "kernel development"
   - When unclear, make reasonable assumptions based on job context

5. **COMPLEX FIELDS (Cover letters, essays):**
   - Write authentically based on actual experience
   - Match tone to role level - emphasize relevant strengths
   - Be confident but honest
   - ONLY use type "textarea" fields for long-form answers (cover letters, detailed explanations)

6. **FIELD LENGTH BY TYPE (CRITICAL):**
   - type "text" = single-line input field. Answer must be SHORT: 1-10 words max. Examples: "Immediate", "3 years", "Auckland", "Yes"
   - type "textarea" = multi-line field. This is where cover letters and detailed answers go.
   - If a "text" field says "Please give details" or similar, give a BRIEF clarification (e.g., "Immediate availability" or "2 weeks notice"), NOT a cover letter
   - NEVER put a cover letter or essay into a type "text" field
"""

class FieldAnswer(BaseModel):
    field_index: int
    answer: str

class FormFieldFiller:
    def __init__(self):
        self.ai_service = AIService()
        self._initialized = False

    async def _ensure_initialized(self):
        if not self._initialized:
            await self.ai_service.initialize()
            self._initialized = True

    def detect_form_fields(self, page: Page) -> List[Dict]:
        fields = []

        modal = page.query_selector('[role="dialog"]')
        if not modal:
            return fields

        text_inputs = modal.query_selector_all(
            'input[type="text"], input[type="email"], input[type="tel"], input[type="number"], input:not([type])')
        for input_elem in text_inputs:
            label = self._get_field_label(input_elem, page)
            if label:
                role = input_elem.get_attribute('role')
                aria_autocomplete = input_elem.get_attribute('aria-autocomplete')
                aria_expanded = input_elem.get_attribute('aria-expanded')

                input_type = input_elem.get_attribute('type')
                input_mode = input_elem.get_attribute('inputmode')
                pattern = input_elem.get_attribute('pattern')
                step_attr = input_elem.get_attribute('step')
                min_attr = input_elem.get_attribute('min')
                max_attr = input_elem.get_attribute('max')
                input_id = input_elem.get_attribute('id') or ''

                has_numeric_pattern = pattern and re.search(r'\\d|[0-9]', pattern)
                has_numeric_constraints = (step_attr is not None) or (min_attr is not None) or (max_attr is not None)

                # LinkedIn uses ID suffix "-numeric" to indicate numeric fields (terrible practice)
                has_linkedin_numeric_id = input_id.endswith('-numeric')

                is_numeric = (
                        (input_type == 'number') or
                        (input_mode in ['numeric', 'decimal']) or
                        has_numeric_pattern or
                        has_numeric_constraints or
                        has_linkedin_numeric_id
                )

                # Detect if field requires decimal vs integer
                # Note: LinkedIn's -numeric suffix just means "numeric", not necessarily decimals
                # GPA fields need decimals, years fields need integers - can't tell from HTML alone
                # step="any" or step with decimal (e.g. "0.1") = decimals allowed
                # inputmode="decimal" = decimals expected
                requires_decimal = (
                    (input_mode == 'decimal') or
                    (step_attr == 'any') or
                    (step_attr and '.' in step_attr)
                )

                if has_linkedin_numeric_id:
                    custom_print("DEBUG", f"  LinkedIn -numeric field detected: '{label}'")

                # Fallback heuristic only if HTML detection failed
                if not is_numeric and label:
                    l_lower = label.lower()
                    numeric_triggers = ['years', 'salary', 'pay', 'compensation', 'how many', 'quantity', 'rate', 'ctc', 'notice period', 'notice']
                    if any(t in l_lower for t in numeric_triggers) and 'phone' not in l_lower:
                        is_numeric = True
                        custom_print("DEBUG", f"  Heuristic fallback: NUMERIC mode for '{label}' (no HTML indicators found)")

                is_autocomplete = (role == 'combobox' or aria_autocomplete is not None or
                                   aria_expanded is not None)

                field_type = "autocomplete" if is_autocomplete else "text"

                maxlength = input_elem.get_attribute('maxlength')
                fields.append({
                    "element": input_elem,
                    "type": field_type,
                    "label": label,
                    "is_numeric": is_numeric,
                    "requires_decimal": requires_decimal,
                    "placeholder": input_elem.get_attribute('placeholder') or "",
                    "required": input_elem.get_attribute('required') is not None,
                    "value": input_elem.get_attribute('value') or "",
                    "maxlength": int(maxlength) if maxlength else None
                })

                if requires_decimal:
                    custom_print("DEBUG", f"  Field requires DECIMAL: '{label}' (step={step_attr}, inputmode={input_mode})")

        textareas = modal.query_selector_all('textarea')
        for textarea in textareas:
            label = self._get_field_label(textarea, page)
            if label:
                maxlength = textarea.get_attribute('maxlength')
                fields.append({
                    "element": textarea,
                    "type": "textarea",
                    "label": label,
                    "is_numeric": False,
                    "placeholder": textarea.get_attribute('placeholder') or "",
                    "required": textarea.get_attribute('required') is not None,
                    "value": textarea.inner_text() or "",
                    "maxlength": int(maxlength) if maxlength else None
                })

        selects = modal.query_selector_all('select')
        for select in selects:
            label = self._get_field_label(select, page)
            options = [opt.inner_text().strip() for opt in select.query_selector_all('option') if
                       opt.inner_text().strip()]
            if label:
                fields.append({
                    "element": select,
                    "type": "select",
                    "label": label,
                    "is_numeric": False,
                    "options": options,
                    "required": select.get_attribute('required') is not None,
                    "value": select.get_attribute('value') or ""
                })

        radio_groups = {}
        radios = modal.query_selector_all('input[type="radio"]')
        for radio in radios:
            name = radio.get_attribute('name')
            if name:
                if name not in radio_groups:
                    label = self._get_radio_group_label(radio, page)

                    if not label:
                        custom_print("WARNING", f"Skipping radio group '{name}' - couldn't detect question text")
                        continue

                    radio_groups[name] = {
                        "name": name,
                        "type": "radio",
                        "label": label,
                        "is_numeric": False,
                        "options": [],
                        "required": radio.get_attribute('required') is not None
                    }

                option_label = self._get_radio_option_label(radio, page)
                if option_label:
                    radio_groups[name]["options"].append(option_label)

        fields.extend(radio_groups.values())

        checkbox_groups = {}
        checkboxes = modal.query_selector_all('input[type="checkbox"]')
        for checkbox in checkboxes:
            name = checkbox.get_attribute('name')
            if name:
                if name not in checkbox_groups:
                    label = self._get_checkbox_group_label(checkbox, page)

                    if not label:
                        # Fallback: use the checkbox name or nearby text
                        label = self._get_field_label(checkbox, page)
                    if not label or label == "Unknown Field":
                        # Last resort: use a readable version of the name attribute
                        label = name.replace('_', ' ').replace('-', ' ') if name else None
                    if not label:
                        custom_print("WARNING", f"Skipping checkbox group '{name}' - couldn't detect question text")
                        continue

                    checkbox_groups[name] = {
                        "name": name,
                        "type": "checkbox",
                        "label": label,
                        "is_numeric": False,
                        "options": [],
                        "required": checkbox.get_attribute('required') is not None or
                                    checkbox.get_attribute('aria-required') == 'true'
                    }

                option_label = self._get_checkbox_option_label(checkbox, page)
                if option_label:
                    checkbox_groups[name]["options"].append(option_label)

        fields.extend(checkbox_groups.values())

        # Debug: dump ALL form elements in modal to find undetected fields
        if fields:
            all_inputs = modal.query_selector_all('input, textarea, select')
            detected_labels = [f.get('label', '') for f in fields]
            custom_print("DEBUG", f"  Modal has {len(all_inputs)} total form elements, detected {len(fields)} fields")
            for elem_idx, elem in enumerate(all_inputs):
                tag = elem.evaluate('el => el.tagName')
                input_type = elem.get_attribute('type') or ''
                name = elem.get_attribute('name') or ''
                visible = elem.is_visible()
                label = self._get_field_label(elem, page)
                # Only log visible elements we didn't detect
                if visible and label and label not in detected_labels and input_type not in ['hidden', 'submit', 'button']:
                    custom_print("WARNING", f"  UNDETECTED field: <{tag} type='{input_type}'> label='{label[:80]}' name='{name[:60]}'")

        return fields

    def _get_field_label(self, element, page) -> str:
        aria_label = element.get_attribute('aria-label')
        if aria_label:
            label = aria_label.strip()
            # If label is vague (e.g. "Please give details."), try to find parent context
            if self._is_vague_label(label):
                parent_context = self._get_parent_question_context(element, page)
                if parent_context:
                    label = f"{parent_context} - {label}"
            return label

        field_id = element.get_attribute('id')
        if field_id:
            label_elem = page.query_selector(f'label[for="{field_id}"]')
            if label_elem:
                label = label_elem.inner_text().strip()
                if self._is_vague_label(label):
                    parent_context = self._get_parent_question_context(element, page)
                    if parent_context:
                        label = f"{parent_context} - {label}"
                return label

        parent = element.evaluate('el => el.closest("label")')
        if parent:
            return page.evaluate('el => el.textContent', parent).strip()

        try:
            prev_text = element.evaluate('''el => {
                const prev = el.previousElementSibling;
                return prev ? prev.textContent : "";
            }''')
            if prev_text and len(prev_text) < 100:
                return prev_text.strip()
        except:
            pass

        placeholder = element.get_attribute('placeholder')
        if placeholder:
            return placeholder

        name = element.get_attribute('name')
        if name:
            return name.replace('_', ' ').replace('-', ' ').title()

        return "Unknown Field"

    def _is_vague_label(self, label: str) -> bool:
        """Check if a label is too vague to understand on its own."""
        vague_labels = [
            'please give details', 'please provide details', 'please specify',
            'please explain', 'give details', 'provide details', 'details',
            'please elaborate', 'other', 'specify', 'if yes, please explain',
            'if other, please specify', 'please describe'
        ]
        return label.lower().rstrip('.').strip() in vague_labels

    def _get_parent_question_context(self, element, page) -> str:
        """Walk up the DOM to find the parent question/group this field belongs to."""
        try:
            context = element.evaluate('''el => {
                // Walk up to find the form-component wrapper
                let current = el.parentElement;
                for (let i = 0; i < 10 && current; i++) {
                    // Look for LinkedIn's form component wrapper
                    const className = current.className || '';

                    // Check if this wrapper has a preceding sibling with a question
                    const prevSibling = current.previousElementSibling;
                    if (prevSibling) {
                        // Look for select/dropdown or radio group in previous sibling
                        const select = prevSibling.querySelector('select');
                        const legend = prevSibling.querySelector('legend, [data-test-form-builder-radio-button-form-component__title]');
                        const label = prevSibling.querySelector('label');

                        if (select) {
                            const selectLabel = prevSibling.querySelector('label');
                            if (selectLabel) {
                                const selectedOption = select.options[select.selectedIndex];
                                const selectedText = selectedOption ? selectedOption.textContent.trim() : '';
                                return selectLabel.textContent.trim() + (selectedText ? ' (selected: ' + selectedText + ')' : '');
                            }
                        }
                        if (legend) return legend.textContent.trim();
                        if (label) return label.textContent.trim();
                    }

                    // Also check for a label/question within the same parent group
                    if (className.includes('form-component') || className.includes('fb-form')) {
                        const labels = current.querySelectorAll('label, legend, span[class*="title"], h3, h4');
                        for (const lbl of labels) {
                            const text = lbl.textContent.trim();
                            if (text && text.length > 3 && text.length < 200
                                && !text.toLowerCase().includes('please give details')
                                && !text.toLowerCase().includes('please provide details')) {
                                return text;
                            }
                        }
                    }

                    current = current.parentElement;
                }
                return '';
            }''')
            return context if context else None
        except:
            return None

    def _get_radio_group_label(self, radio_element, page) -> str:
        try:
            question_text = radio_element.evaluate('''el => {
                const fieldset = el.closest('fieldset[data-test-form-builder-radio-button-form-component]');
                if (fieldset) {
                    const titleSpan = fieldset.querySelector('[data-test-form-builder-radio-button-form-component__title]');
                    if (titleSpan) {
                        const innerSpan = titleSpan.querySelector('span[aria-hidden="true"]');
                        if (innerSpan && innerSpan.textContent.trim().length > 3) {
                            return innerSpan.textContent.trim();
                        }
                        if (titleSpan.textContent.trim().length > 3) {
                            return titleSpan.textContent.trim();
                        }
                    }

                    const legend = fieldset.querySelector('legend');
                    if (legend && legend.textContent.trim().length > 3) {
                        return legend.textContent.trim();
                    }

                    const labels = fieldset.querySelectorAll('label, span[class*="label"], div[class*="label"], h3, h4');
                    for (let label of labels) {
                        const text = label.textContent.trim();
                        if (text && text.toLowerCase() !== 'yes' && text.toLowerCase() !== 'no' && text.length > 3) {
                            return text;
                        }
                    }
                }

                return "";
            }''')

            if question_text and len(question_text) > 3:
                return question_text

            return None
        except Exception as e:
            custom_print("DEBUG", f"Radio label detection error: {str(e)[:100]}")
            return None

    def _get_radio_option_label(self, radio_element, page) -> str:
        try:
            radio_id = radio_element.get_attribute('id')
            if radio_id:
                label = page.query_selector(f'label[for="{radio_id}"]')
                if label:
                    return label.inner_text().strip()

            next_text = radio_element.evaluate('''el => {
                const next = el.nextElementSibling;
                return next ? next.textContent : "";
            }''')
            if next_text:
                return next_text.strip()

            return radio_element.get_attribute('value') or ""
        except:
            return ""

    def _get_checkbox_group_label(self, checkbox_element, page) -> str:
        try:
            question_text = checkbox_element.evaluate('''el => {
                const fieldset = el.closest('fieldset[data-test-checkbox-form-component]');
                if (fieldset) {
                    const titleDiv = fieldset.querySelector('[data-test-checkbox-form-title]');
                    if (titleDiv) {
                        const innerSpan = titleDiv.querySelector('span[aria-hidden="true"]');
                        if (innerSpan && innerSpan.textContent.trim().length > 3) {
                            return innerSpan.textContent.trim();
                        }
                        if (titleDiv.textContent.trim().length > 3) {
                            return titleDiv.textContent.trim();
                        }
                    }

                    const legend = fieldset.querySelector('legend');
                    if (legend) {
                        const legendText = legend.textContent.trim();
                        if (legendText.length > 3) {
                            return legendText;
                        }
                    }

                    const labels = fieldset.querySelectorAll('label:not([data-test-text-selectable-option__label]), div[class*="label"], h3, h4');
                    for (let label of labels) {
                        const text = label.textContent.trim();
                        // Relaxed length check to catch short labels like "Present" or "Current"
                        if (text && text.length > 2) { 
                            return text;
                        }
                    }
                }

                return "";
            }''')

            if question_text and len(question_text) > 2:
                return question_text

            return None
        except Exception as e:
            custom_print("DEBUG", f"Checkbox label detection error: {str(e)[:100]}")
            return None

    def _get_checkbox_option_label(self, checkbox_element, page) -> str:
        try:
            data_attr = checkbox_element.get_attribute('data-test-text-selectable-option__input')
            if data_attr:
                return data_attr.strip()

            checkbox_id = checkbox_element.get_attribute('id')
            if checkbox_id:
                label = page.query_selector(f'label[for="{checkbox_id}"]')
                if label:
                    return label.inner_text().strip()

            next_text = checkbox_element.evaluate('''el => {
                const next = el.nextElementSibling;
                if (next && next.tagName === 'LABEL') {
                    return next.textContent;
                }
                return "";
            }''')
            if next_text:
                return next_text.strip()

            return checkbox_element.get_attribute('value') or ""
        except:
            return ""

    class FormFieldAnswers(BaseModel):
        model_config = ConfigDict(extra='allow')
        answers: List[FieldAnswer]
        complex_fields: List[Dict] = []
        reasoning: str

    async def generate_field_answers(self, fields: List[Dict], job_title: str, company: str,
                                     job_description: str = None) -> Dict:
        await self._ensure_initialized()

        fields_summary = []
        for idx, field in enumerate(fields):
            field_info = {
                "index": idx,
                "type": field['type'],
                "label": field['label'],
                "required": field.get('required', False),
                "format": "NUMERIC_ONLY" if field.get('is_numeric') else "text"
            }

            if field['type'] in ['select', 'radio', 'checkbox']:
                field_info['options'] = field.get('options', [])

            if field.get('placeholder'):
                field_info['placeholder'] = field['placeholder']

            if field.get('maxlength'):
                field_info['maxlength'] = field['maxlength']

            fields_summary.append(field_info)

        triage_prompt = f"""
You are a smart form-filling assistant representing the Candidate.

**Job Details:**
Title: {job_title}
Company: {company}

**Job Description:**
{job_description or 'No description available'}

**Candidate Data (JSON source of truth):**
{json.dumps(CV_SUPPLEMENTARY, indent=2)}

**Full CV (Reference):**
{CV_FULL_TEXT}

**Form Fields:**
{json.dumps(fields_summary, indent=2)}

**Your Task:**
Handle EVERY field in the list above.

{FIELD_RULES}

Return JSON with "answers" as a LIST of objects:
{{
    "answers": [
        {{"field_index": 0, "answer": "answer for field 0"}},
        {{"field_index": 1, "answer": "answer for field 1"}}
    ],
    "complex_fields": [3, 5],
    "reasoning": "Brief explanation"
}}
"""

        try:
            custom_print("FORM", f"Analyzing {len(fields)} form fields with AI...")

            class PermissiveStage1(BaseModel):
                model_config = ConfigDict(extra='allow')
                answers: List[FieldAnswer]
                complex_fields: List[object]
                reasoning: str

            stage1 = await self.ai_service.call_gemini_structured(
                prompt=triage_prompt,
                response_schema=PermissiveStage1,
                model=settings.GEMINI_MODEL_FORMS,
                temperature=settings.GEMINI_TEMPERATURE
            )

            answers = {}
            for item in stage1.get('answers', []):
                idx = item['field_index'] if isinstance(item, dict) else item.field_index
                val = item['answer'] if isinstance(item, dict) else item.answer

                if 0 <= idx < len(fields):
                    answers[idx] = val

            complex_indices_raw = stage1.get('complex_fields', [])

            normalized_indices = []
            for item in complex_indices_raw:
                if isinstance(item, int):
                    normalized_indices.append(item)
                elif isinstance(item, dict):
                    val = item.get('field_index') or item.get('index')
                    if val is not None:
                        normalized_indices.append(int(val))
                elif isinstance(item, str) and item.isdigit():
                    normalized_indices.append(int(item))

            if normalized_indices:
                custom_print("FORM", f"Stage 2: Pro writing {len(normalized_indices)} complex fields...")

                complex_fields_info = [
                    {**fields_summary[idx], "current_answer": answers.get(idx, "")}
                    for idx in normalized_indices
                    if 0 <= idx < len(fields_summary)
                ]

                if complex_fields_info:
                    pro_prompt = f"""
You are a professional cover letter and essay writer.

**Job Details:**
Title: {job_title}
Company: {company}

**Job Description:**
{job_description or 'No description available'}

**Candidate Data (JSON Source of Truth):**
{json.dumps(CV_SUPPLEMENTARY, indent=2)}

**Full CV (Reference):**
{CV_FULL_TEXT}

**Complex Fields to Write:**
{json.dumps(complex_fields_info, indent=2)}

{FIELD_RULES}

**Your Task:**
Answer the complex fields listed above using your intelligence and the rules defined above.

**CRITICAL: ONLY return answers for the field indices listed above. Do NOT add extra fields.**

Return JSON with answers as a LIST of objects:
{{
    "answers": [
        {{"field_index": 3, "answer": "Detailed answer..."}}
    ],
    "reasoning": "Brief explanation"
}}
"""

                    class ComplexFieldAnswers(BaseModel):
                        model_config = ConfigDict(extra='allow')
                        answers: List[FieldAnswer]
                        reasoning: str

                    pro_result = await self.ai_service.call_gemini_structured(
                        prompt=pro_prompt,
                        response_schema=ComplexFieldAnswers,
                        model=settings.GEMINI_MODEL_COVER,
                        temperature=settings.GEMINI_TEMPERATURE
                    )

                    # Handle Pro returning either {answers: [...]} or a raw list
                    if isinstance(pro_result, list):
                        pro_answers = pro_result
                    else:
                        pro_answers = pro_result.get('answers', [])

                    for item in pro_answers:
                        idx = item['field_index'] if isinstance(item, dict) else item.field_index
                        val = item['answer'] if isinstance(item, dict) else item.answer

                        if 0 <= idx < len(fields):
                            answers[idx] = val

                    custom_print("FORM", f"Pro enhanced {len(pro_answers)} fields")

            return {
                "answers": answers,
                "reasoning": stage1.get('reasoning', ''),
                "cover_letter": ""
            }

        except Exception as e:
            custom_print("ERROR", f"AI form filling failed: {str(e)}")
            custom_print("ERROR", "Cannot proceed - AI is required for accurate form filling")
            raise RuntimeError(f"AI form filling failed: {str(e)}") from e

    async def fix_validation_errors(self, fields: List[Dict], current_answers: Dict, error_messages: List[str]) -> Dict:
        await self._ensure_initialized()

        custom_print("AI_FIX", f"Attempting to fix {len(error_messages)} validation errors...")

        fields_summary = []
        for idx, field in enumerate(fields):
            fields_summary.append({
                "index": idx,
                "label": field['label'],
                "type": field['type'],
                "current_answer": current_answers.get(idx, "NO ANSWER PROVIDED"),
                "options": field.get('options', [])
            })

        prompt = f"""
        **EMERGENCY FIX MODE**
        I tried to fill a form, but the website rejected some answers with these errors:

        **ERRORS SEEN ON SCREEN:**
        {json.dumps(error_messages, indent=2)}

        **FORM STATE:**
        {json.dumps(fields_summary, indent=2)}

        **Candidate Data:**
        {json.dumps(CV_SUPPLEMENTARY)}

        **INSTRUCTIONS:**
        1. Map each error message to the field that likely caused it.
        2. Provide a NEW, CORRECTED answer that satisfies the validation.
        3. Common fixes:
           - "Enter a decimal number" → use "10.0" not "10"
           - "Enter a valid number" → use digits only, no text like "Immediate"
           - "Enter a whole number between 0 and 99" → use integer like "10"

        **REQUIRED OUTPUT FORMAT (exactly this structure):**
        {{"answers": [{{"field_index": 0, "answer": "corrected value"}}, ...], "reasoning": "brief explanation"}}
        """

        try:
            class FormFieldAnswers(BaseModel):
                model_config = ConfigDict(extra='allow')
                answers: List[FieldAnswer]
                reasoning: str

            result = await self.ai_service.call_gemini_structured(
                prompt=prompt,
                response_schema=FormFieldAnswers,
                model=settings.GEMINI_MODEL_FORMS,
                temperature=0.1  # Low temp for strict logic
            )

            # Handle both formats: {"answers": [...]} or raw list [...]
            if isinstance(result, list):
                answers_list = result
            elif isinstance(result, dict):
                answers_list = result.get('answers', [])
            else:
                custom_print("ERROR", f"Unexpected result type: {type(result)}")
                return current_answers

            # Merge new fixes into current answers
            fixed_answers = current_answers.copy()
            for item in answers_list:
                if isinstance(item, dict):
                    # Handle key variations: field_index/index, answer/new_answer
                    idx = item.get('field_index', item.get('index'))
                    val = item.get('answer', item.get('new_answer'))
                else:
                    idx = item.field_index
                    val = item.answer

                if idx is not None and val is not None:
                    fixed_answers[idx] = val
                    custom_print("AI_FIX", f"  Refining Field {idx}: '{val}'")

            return fixed_answers

        except Exception as e:
            custom_print("ERROR", f"Self-healing failed: {e}")
            return current_answers

    def fill_fields(self, page: Page, fields: List[Dict], answers: Dict):
        custom_print("FORM", f"Filling {len(answers)} form fields...")

        for idx, field in enumerate(fields):
            if idx not in answers:
                continue

            answer = answers[idx]
            question = field.get('label', 'Unknown field')

            try:
                if field['type'] in ['radio', 'checkbox']:
                    element = None
                else:
                    element = field.get('element')
                    if not element:
                        custom_print("WARNING", f"No element found for field: {question}")
                        continue

                if field['type'] in ['text', 'email', 'tel', 'number', 'autocomplete']:
                    value_to_fill = str(answer)

                    if field.get('is_numeric', False):
                        clean_val = re.sub(r'[^\d.]', '', value_to_fill)
                        if clean_val:
                            requires_decimal = field.get('requires_decimal', False)

                            if requires_decimal:
                                # Field explicitly requires decimal - ensure .0 suffix
                                if '.' not in clean_val:
                                    clean_val = f"{clean_val}.0"
                                    custom_print("DEBUG", f"  Added decimal: '{value_to_fill}' -> '{clean_val}'")
                                else:
                                    custom_print("DEBUG", f"  Keeping decimal: '{clean_val}'")
                            elif 'year' in field.get('label', '').lower():
                                # Years field without explicit decimal requirement
                                if '.' not in str(value_to_fill):
                                    # AI gave integer, keep as integer
                                    try:
                                        clean_val = str(int(round(float(clean_val))))
                                        custom_print("DEBUG", f"  Rounded years field: '{value_to_fill}' -> '{clean_val}'")
                                    except:
                                        pass
                                else:
                                    # AI gave decimal - trust it (validation may have required it)
                                    custom_print("DEBUG", f"  Keeping AI decimal: '{clean_val}'")
                            else:
                                custom_print("DEBUG", f"  Cleaned numeric field: '{value_to_fill}' -> '{clean_val}'")
                            value_to_fill = clean_val
                        else:
                            custom_print("DEBUG",
                                         f"  Warning: Numeric field became empty after cleaning '{value_to_fill}', defaulting to 0")
                            value_to_fill = "0"

                    element.fill(value_to_fill)
                    if field['type'] != 'autocomplete':
                        # Dispatch events so LinkedIn's React picks up the value
                        # Skip for autocomplete - blur would close the dropdown
                        element.evaluate('''el => {
                            el.dispatchEvent(new Event('input', { bubbles: true }));
                            el.dispatchEvent(new Event('change', { bubbles: true }));
                            el.dispatchEvent(new Event('blur', { bubbles: true }));
                        }''')
                        time.sleep(0.3)
                        custom_print("FORM", f"✓ Filled text: '{value_to_fill[:60]}...' for '{question[:50]}'") if len(value_to_fill) > 60 else custom_print("FORM", f"✓ Filled text: '{value_to_fill}' for '{question[:50]}'")

                    if field['type'] == 'autocomplete':
                        time.sleep(1.0)

                        try:
                            autocomplete_selectors = [
                                '[role="listbox"] [role="option"]',
                                '.basic-typeahead__triggered-content [role="option"]',
                                'ul[role="listbox"] li',
                                '.typeahead-results li',
                                '[data-test-typeahead-result]'
                            ]

                            suggestions = []
                            active_selector = None
                            for selector in autocomplete_selectors:
                                elements = page.query_selector_all(selector)
                                if elements and len(elements) > 0:
                                    suggestions = [el.inner_text().strip() for el in elements if
                                                   el.inner_text().strip()]
                                    if suggestions:
                                        active_selector = selector
                                        custom_print("DEBUG",
                                                     f"  Found {len(suggestions)} autocomplete options: {suggestions[:3]}...")
                                        break

                            if suggestions and active_selector:
                                best_match = suggestions[0]
                                selected_index = 0
                                for i, suggestion in enumerate(suggestions):
                                    if str(answer).lower() in suggestion.lower():
                                        best_match = suggestion
                                        selected_index = i
                                        break

                                option_elements = page.query_selector_all(active_selector)
                                if selected_index < len(option_elements):
                                    option_elements[selected_index].click()
                                    time.sleep(0.5)
                                    custom_print("FORM", f"✓ Selected autocomplete: '{best_match}'")
                            else:
                                custom_print("DEBUG", f"  No autocomplete suggestions found, using keyboard fallback")
                                element.press('ArrowDown')
                                time.sleep(0.3)
                                element.press('Enter')
                        except Exception as e:
                            custom_print("WARNING", f"Autocomplete selection failed: {str(e)[:50]}")

                elif field['type'] == 'textarea':
                    text_val = str(answer)
                    maxlength = field.get('maxlength')
                    if maxlength and len(text_val) > maxlength:
                        custom_print("WARNING", f"Textarea '{question[:50]}' exceeds maxlength ({len(text_val)}/{maxlength}), truncating")
                        text_val = text_val[:maxlength]
                    element.fill(text_val)
                    element.evaluate('''el => {
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                        el.dispatchEvent(new Event('blur', { bubbles: true }));
                    }''')
                    time.sleep(0.3)
                    custom_print("FORM", f"✓ Filled textarea: {len(text_val)} chars for '{question[:50]}'")


                elif field['type'] == 'select':
                    options = field.get('options', [])
                    matched = False
                    answer_clean = str(answer).strip()

                    # Pass 1: exact match (case-insensitive)
                    match_idx = None
                    for idx, option in enumerate(options):
                        if answer_clean.lower() == option.strip().lower():
                            match_idx = idx
                            break

                    # Pass 2: substring match (only if no exact match)
                    if match_idx is None:
                        for idx, option in enumerate(options):
                            option_clean = option.strip()
                            if answer_clean.lower() in option_clean.lower() or option_clean.lower() in answer_clean.lower():
                                match_idx = idx
                                break

                    if match_idx is not None:
                        select_idx = match_idx
                        option_clean = options[select_idx].strip()
                        try:
                            page.evaluate(
                                f"(el) => {{ el.selectedIndex = {select_idx}; el.dispatchEvent(new Event('change', {{ bubbles: true }})); el.dispatchEvent(new Event('input', {{ bubbles: true }})); }}",
                                element)
                            time.sleep(0.5)
                            custom_print("FORM", f"✓ Selected dropdown: '{option_clean}' for '{question[:50]}'")
                            matched = True
                        except Exception as e:
                            custom_print("WARNING", f"Dropdown JS failed for '{question}': {str(e)[:50]}")
                            try:
                                element.select_option(label=options[select_idx], timeout=1000)
                                matched = True
                            except:
                                pass

                    if not matched:
                        custom_print("WARNING", f"Could not select '{answer}' in '{question}'")

                elif field['type'] == 'radio':
                    try:
                        name = field.get('name')
                        options = field.get('options', [])

                        custom_print("DEBUG", f"  Radio: name='{name}', options={options}, answer='{answer}'")

                        selected_index = None
                        for idx, option in enumerate(options):
                            if str(answer).lower() in option.lower() or option.lower() in str(answer).lower():
                                selected_index = idx
                                custom_print("DEBUG", f"  Radio: matched '{answer}' to option {idx}: '{option}'")
                                break

                        if selected_index is not None and name:
                            all_radios = page.query_selector_all(f'input[type="radio"][name="{name}"]')
                            custom_print("DEBUG", f"  Radio: found {len(all_radios)} radio buttons with name='{name}'")

                            if selected_index < len(all_radios):
                                custom_print("DEBUG", f"  Radio: attempting to click radio at index {selected_index}")
                                try:
                                    page.evaluate('''(el) => {
                                        el.click();
                                        el.dispatchEvent(new Event('change', { bubbles: true }));
                                        el.dispatchEvent(new Event('input', { bubbles: true }));
                                    }''', all_radios[selected_index])
                                    time.sleep(0.5)
                                    custom_print("FORM",
                                                 f"✓ Selected radio: {options[selected_index]} for '{question[:50]}'")
                                except Exception as click_error:
                                    custom_print("ERROR", f"  Radio click failed: {click_error}")
                                    raise
                            else:
                                custom_print("WARNING",
                                             f"Radio index {selected_index} out of range (have {len(all_radios)} radios)")
                        else:
                            custom_print("WARNING", f"Could not match '{answer}' to radio options {options}")
                    except Exception as radio_error:
                        custom_print("ERROR", f"Radio button error: {radio_error}")

                elif field['type'] == 'checkbox':
                    try:
                        if not answer or (isinstance(answer, str) and not answer.strip()):
                            custom_print("DEBUG", f"  Checkbox: skipping empty answer for '{question[:50]}'")
                            continue

                        name = field.get('name')
                        options = field.get('options', [])

                        custom_print("DEBUG", f"  Checkbox: name='{name}', options={options[:5]}..., answer='{answer}'")

                        if isinstance(answer, str):
                            answer_parts = [a.strip() for a in
                                            answer.replace(' and ', ',').replace('\n', ',').split(',')]
                        elif isinstance(answer, list):
                            answer_parts = answer
                        else:
                            answer_parts = [str(answer)]

                        selected_indices = []
                        for answer_part in answer_parts:
                            if not answer_part:
                                continue
                            for idx, option in enumerate(options):
                                if answer_part.lower() in option.lower() or option.lower() in answer_part.lower():
                                    if idx not in selected_indices:
                                        selected_indices.append(idx)
                                        custom_print("DEBUG",
                                                     f"  Checkbox: matched '{answer_part}' to option {idx}: '{option}'")

                        if selected_indices and name:
                            all_checkboxes = page.query_selector_all(f'input[type="checkbox"][name="{name}"]')
                            custom_print("DEBUG",
                                         f"  Checkbox: found {len(all_checkboxes)} checkboxes with name='{name}'")

                            for idx in selected_indices:
                                if idx < len(all_checkboxes):
                                    try:
                                        page.evaluate('''(el) => {
                                            if (!el.checked) {
                                                el.click();
                                                el.dispatchEvent(new Event('change', { bubbles: true }));
                                                el.dispatchEvent(new Event('input', { bubbles: true }));
                                            }
                                        }''', all_checkboxes[idx])
                                        time.sleep(0.3)
                                        custom_print("FORM", f"✓ Checked: {options[idx]} for '{question[:50]}'")
                                    except Exception as click_error:
                                        custom_print("ERROR",
                                                     f"  Checkbox click failed for {options[idx]}: {click_error}")
                                else:
                                    custom_print("WARNING",
                                                 f"Checkbox index {idx} out of range (have {len(all_checkboxes)} checkboxes)")
                        else:
                            custom_print("WARNING", f"Could not match '{answer}' to checkbox options {options[:5]}...")
                    except Exception as checkbox_error:
                        custom_print("ERROR", f"Checkbox error: {checkbox_error}")

            except Exception as e:
                custom_print("ERROR", f"Failed to fill '{question}': {str(e)}")