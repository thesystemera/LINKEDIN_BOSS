(opts) => {
  opts = opts || {};
  const PFX = opts.prefix || 'f';
  const ROOT_SEL = opts.rootSelector || null;
  const STRICT = !!opts.strictRoot;
  const MAX_LABEL = 500;

  const clean = s => (s || '').replace(/[​ ]/g, ' ').replace(/\s+/g, ' ').trim();
  const txt = el => el ? clean(el.innerText !== undefined && el.offsetParent !== null ? el.innerText : el.textContent) : '';

  function deepAll(root, sel) {
    const out = [];
    const visit = node => {
      if (!node) return;
      if (node.querySelectorAll) node.querySelectorAll(sel).forEach(e => out.push(e));
      const all = node.querySelectorAll ? node.querySelectorAll('*') : [];
      all.forEach(e => { if (e.shadowRoot) visit(e.shadowRoot); });
    };
    visit(root);
    return out;
  }

  function byId(el, id) {
    if (!id) return null;
    const r = el.getRootNode ? el.getRootNode() : document;
    return (r.getElementById ? r.getElementById(id) : null) || document.getElementById(id);
  }

  function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return false;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none' || parseFloat(cs.opacity) === 0) return false;
    return true;
  }

  function isRendered(el) {
    let e = el;
    while (e && e.nodeType === 1) {
      const cs = getComputedStyle(e);
      if (cs.display === 'none' || cs.visibility === 'hidden') return false;
      e = e.parentElement || (e.getRootNode && e.getRootNode().host) || null;
    }
    return true;
  }

  function visibleOrProxy(el) {
    if (isVisible(el)) return true;
    const lab = el.id ? deepAll(document, `label[for="${CSS.escape(el.id)}"]`)[0] : null;
    if (lab && isVisible(lab)) return true;
    const wrap = el.closest('label');
    if (wrap && isVisible(wrap)) return true;
    const p = el.parentElement;
    return !!(p && isVisible(p) && isRendered(el.parentElement));
  }

  const CONTROL_SEL = 'input, textarea, select, [role="combobox"], [role="radio"], [role="checkbox"], [role="switch"], [role="spinbutton"], [contenteditable="true"], button[aria-haspopup="listbox"], button[aria-pressed]';
  const SKIP_TYPES = new Set(['hidden', 'submit', 'button', 'image', 'reset', 'password', 'range', 'color']);

  function findRoot() {
    if (ROOT_SEL) {
      const cands = deepAll(document, ROOT_SEL).filter(isVisible);
      if (cands.length) {
        cands.sort((a, b) => deepAll(b, CONTROL_SEL).length - deepAll(a, CONTROL_SEL).length);
        return cands[0];
      }
      if (STRICT) return null;
    }
    const dialogs = deepAll(document, '[role="dialog"], [aria-modal="true"], dialog[open]').filter(isVisible)
      .filter(d => deepAll(d, CONTROL_SEL).length > 0 || /apply|application/i.test(txt(d).slice(0, 300)));
    if (dialogs.length) return dialogs[dialogs.length - 1];
    return document.body;
  }

  const root = findRoot();
  if (!root) return { url: location.href, title: document.title, rootTag: 'none', fields: [], buttons: [], errors: [], headings: [], progress: null, success: false, captcha: false, rootText: '' };
  deepAll(document, '[data-lb-fid],[data-lb-bid],[data-lb-opt],[data-lb-grp]').forEach(e => {
    e.removeAttribute('data-lb-fid'); e.removeAttribute('data-lb-bid'); e.removeAttribute('data-lb-opt'); e.removeAttribute('data-lb-grp');
  });

  function controlKind(el) {
    const tag = el.tagName.toLowerCase();
    const role = (el.getAttribute('role') || '').toLowerCase();
    const type = (el.getAttribute('type') || (tag === 'input' ? 'text' : '')).toLowerCase();
    if (tag === 'button') {
      if (el.getAttribute('aria-haspopup') === 'listbox') return 'combobox';
      if (el.hasAttribute('aria-pressed')) return 'toggle';
      if (role === 'radio') return 'radio';
      if (role === 'checkbox' || role === 'switch') return 'checkbox';
      return null;
    }
    if (tag === 'select') return 'select';
    if (tag === 'textarea') return 'textarea';
    if (el.getAttribute('contenteditable') === 'true') return 'textarea';
    if (tag === 'input') {
      if (SKIP_TYPES.has(type)) return null;
      if (type === 'file') return 'file';
      if (type === 'radio') return 'radio';
      if (type === 'checkbox') return 'checkbox';
      if (type === 'date' || type === 'month') return 'date';
      if (role === 'combobox' || el.getAttribute('aria-autocomplete') === 'list' || el.getAttribute('aria-autocomplete') === 'both') return 'combobox';
      // typeaheads without ARIA (Lever location): a suggestion list next to the input
      if (el.parentElement && el.parentElement.querySelector('[class*="dropdown-results"]')) return 'combobox';
      if (type === 'search' && !el.closest('form, [role="dialog"], dialog')) return null;
      return 'text';
    }
    if (role === 'combobox') return 'combobox';
    if (role === 'radio') return 'radio';
    if (role === 'checkbox' || role === 'switch') return 'checkbox';
    if (role === 'spinbutton') return 'text';
    return null;
  }

  const TEXT_SKIP = 'input, select, textarea, option, [role="option"], [role="listbox"], [role="alert"], .visually-hidden, .a11y-text, [class*="sr-only"], script, style, svg, [aria-live]';
  function visibleText(node) {
    let out = '';
    for (const c of node.childNodes) {
      if (c.nodeType === 3) { out += ' ' + c.textContent; continue; }
      if (c.nodeType !== 1) continue;
      if (c.matches(TEXT_SKIP)) continue;
      const cs = getComputedStyle(c);
      if (cs.display === 'none' || cs.visibility === 'hidden') continue;
      out += ' ' + visibleText(c);
    }
    return out;
  }
  // inline validation messages without role=alert (LinkedIn) must never become a field's label
  const ERR_TXT = /\b(this field is required|this is a required field|this question is required|an answer is required)\b\.?/gi;
  function ownText(el, exclude) {
    if (!el) return '';
    let t = clean(visibleText(el).replace(ERR_TXT, ' '));
    (exclude || []).forEach(x => { if (x && x.length > 0) t = t.split(x).join(' '); });
    return clean(t);
  }

  function labelledBy(el) {
    const ids = (el.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean);
    return clean(ids.map(id => { const n = byId(el, id); return n ? ownText(n) || clean(n.textContent) : ''; }).join(' '));
  }

  function labelFor(el) {
    if (el.id) {
      const rootNode = el.getRootNode ? el.getRootNode() : document;
      const l = (rootNode.querySelector ? rootNode.querySelector(`label[for="${CSS.escape(el.id)}"]`) : null) || document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (l) return ownText(l) || clean(l.textContent);
    }
    const wrap = el.closest('label');
    if (wrap) return ownText(wrap) || clean(wrap.textContent);
    return '';
  }

  function directLabel(el) {
    return labelledBy(el) || labelFor(el) || clean(el.getAttribute('aria-label')) || clean(el.getAttribute('title'));
  }

  const allControls = deepAll(root, CONTROL_SEL).filter(el => controlKind(el));
  const controlSet = new Set(allControls);

  function controlsIn(node) {
    let n = 0;
    for (const c of allControls) if (node.contains(c)) n++;
    return n;
  }

  function fieldContainer(members) {
    let node = members[0];
    let best = node.parentElement;
    let p = node.parentElement;
    let depth = 0;
    while (p && p !== root && depth < 8) {
      const inside = allControls.filter(c => p.contains(c));
      const foreign = inside.filter(c => !members.includes(c));
      if (foreign.length > 0) break;
      best = p;
      if (p.matches && p.matches('fieldset, [role="group"], [role="radiogroup"], [data-test-form-element], .fb-dash-form-element, [data-automation-id^="formField"], [data-field-path], .application-question, .field, .form-group, .form-field')) break;
      p = p.parentElement;
      depth++;
    }
    return best;
  }

  function precedingText(el, stopAt) {
    let node = el;
    let depth = 0;
    while (node && node !== stopAt && depth < 6) {
      let sib = node.previousElementSibling;
      while (sib) {
        if (!deepAll(sib, CONTROL_SEL).some(c => controlSet.has(c))) {
          const t = ownText(sib);
          if (t && t.length > 1 && t.length < MAX_LABEL) return t;
        } else break;
        sib = sib.previousElementSibling;
      }
      node = node.parentElement;
      depth++;
    }
    return '';
  }

  function questionFor(members, container, optionTexts) {
    const first = members[0];
    const fs = first.closest('fieldset');
    if (fs && container && (fs === container || container.contains(fs) || fs.contains(container))) {
      const lg = fs.querySelector('legend');
      if (lg) { const t = ownText(lg); if (t) return t; }
    }
    const group = first.closest('[role="radiogroup"], [role="group"]');
    if (group) {
      const t = labelledBy(group) || clean(group.getAttribute('aria-label'));
      if (t) return t;
    }
    if (container) {
      const cand = container.querySelector('legend, label:not(:has(input)), [class*="label"]:not(:has(input)), [class*="question"]:not(:has(input)), [class*="title"]:not(:has(input)), h3, h4, [data-test-text-entity-list-form-title], [data-test-checkbox-form-title], [data-test-form-builder-radio-button-form-component__title]');
      if (cand) {
        const t = ownText(cand, optionTexts);
        if (t && t.length < MAX_LABEL) return t;
      }
      const t = ownText(container, optionTexts);
      if (t && t.length < MAX_LABEL) return t;
    }
    return precedingText(container || first, root);
  }

  // heading-like texts of the groups around a field, outermost first, e.g. "Edit experience › Dates of employment › From"
  function sectionPath(el, own) {
    const parts = [];
    let child = el, p = el.parentElement, depth = 0;
    while (p && p !== root && depth < 10 && controlsIn(p) <= 15) {
      let lead = '';
      for (const c of p.children) {
        if (c === child) break;
        // another field's label is not a section heading (flat forms put labels and inputs side by side)
        if (controlsIn(c) > 0 || c.matches('label') || c.querySelector('label')) continue;
        const t = ownText(c);
        if (t && t.length > 1 && t.length <= 60 && !/percent complete|^\d+\s*\/\s*\d+ pages?$/i.test(t)) lead = t;
      }
      if (lead && lead !== own && !parts.includes(lead)) parts.unshift(lead);
      child = p; p = p.parentElement; depth++;
    }
    return parts.slice(-3).join(' › ');
  }

  function isRequired(els, label, container) {
    for (const e of els) {
      if (e.required || e.getAttribute('aria-required') === 'true' || e.hasAttribute('required')) return true;
    }
    if (/\*|✱|\(required\)|required/i.test(label || '')) return true;
    if (container && container.querySelector('[data-test-checkbox-form-required], [data-test-text-entity-list-form-required], [class*="required"], abbr[title="required"]')) return true;
    return false;
  }

  function errorsFor(els, container) {
    const out = new Set();
    for (const e of els) {
      ['aria-errormessage', 'aria-describedby'].forEach(a => {
        (e.getAttribute(a) || '').split(/\s+/).filter(Boolean).forEach(id => {
          const n = byId(e, id);
          if (n && isVisible(n)) {
            const t = clean(n.innerText);
            if (t && (a === 'aria-errormessage' || /error|invalid|required|please|must|enter/i.test(t + ' ' + (n.className || '')))) out.add(t);
          }
        });
      });
    }
    if (container) {
      container.querySelectorAll('[role="alert"], .artdeco-inline-feedback--error, [data-test-form-element-error-messages], [class*="error"], [class*="Error"], [id*="error"], [data-automation-id*="error"]').forEach(n => {
        if (!isVisible(n)) return;
        if (n.querySelector && n.querySelector('input, select, textarea')) return;
        const t = clean(n.innerText);
        if (t && t.length < 300) out.add(t);
      });
      (clean(visibleText(container)).match(ERR_TXT) || []).forEach(t => out.add(clean(t)));
    }
    return [...out].slice(0, 4);
  }

  // an aria-label repeated on every option of a group is the group's question, not the option's label (LinkedIn radios)
  function sharedAria(group) {
    const a = group.length > 1 ? clean(group[0].getAttribute('aria-label')) : '';
    return a && group.every(m => clean(m.getAttribute('aria-label')) === a) ? a : '';
  }

  function optionLabel(el, _i, group) {
    group = group || [el];
    const t = labelFor(el) || (sharedAria(group) ? '' : clean(el.getAttribute('aria-label'))) || labelledBy(el);
    if (t) return t;
    if (el.tagName === 'BUTTON' || el.getAttribute('role')) return clean(el.innerText || el.textContent);
    const v = el.getAttribute('value');
    if (v && !/^(on|true|false)$/i.test(v)) return v;
    const sib = el.nextElementSibling;
    if (sib && ownText(sib)) return ownText(sib);
    // text of the nearest wrapper that holds only this option
    for (let p = el.parentElement, i = 0; p && i < 4 && !group.some(m => m !== el && p.contains(m)); p = p.parentElement, i++) {
      const w = ownText(p);
      if (w) return w;
    }
    return clean(el.parentElement ? el.parentElement.innerText : '');
  }

  function numericInfo(el) {
    const type = (el.getAttribute('type') || '').toLowerCase();
    const im = (el.getAttribute('inputmode') || '').toLowerCase();
    const pattern = el.getAttribute('pattern') || '';
    const step = el.getAttribute('step');
    const id = el.id || '';
    const numeric = type === 'number' || im === 'numeric' || im === 'decimal' || /\\d|\[0-9\]/.test(pattern) || id.endsWith('-numeric') || el.getAttribute('role') === 'spinbutton';
    const decimal = im === 'decimal' || step === 'any' || (!!step && step.includes('.'));
    return { numeric, decimal, min: el.getAttribute('min'), max: el.getAttribute('max') };
  }

  function currentComboValue(el, container) {
    if (el.tagName === 'BUTTON') {
      const t = clean(el.innerText || el.textContent);
      return /^(select( one)?|choose|please select|--|—)\b/i.test(t) || !t ? '' : t;
    }
    const v = clean(el.value);
    if (v) return v;
    if (container) {
      const sv = container.querySelector('[class*="single-value"], [class*="singleValue"], [class*="selected-value"], [data-automation-id="selectedItem"], [class*="__value"]:not([class*="container"])');
      if (sv) return clean(sv.innerText);
      const pills = container.querySelectorAll('[data-automation-id="selectedItem"], [class*="multi-value__label"], [class*="multiValue"] [class*="label"]');
      if (pills.length) return [...pills].map(p => clean(p.innerText)).join('; ');
    }
    return '';
  }

  const fields = [];
  const groupsDone = new Set();
  let n = 0;
  const nextId = () => `${PFX}${n++}`;

  for (const el of allControls) {
    if (groupsDone.has(el)) continue;
    const kind = controlKind(el);
    if (!kind) continue;
    if (kind !== 'file' && !visibleOrProxy(el)) continue;
    if (kind === 'file' && !isRendered(el.parentElement || el)) continue;
    if (el.disabled && kind !== 'radio' && kind !== 'checkbox') continue;
    if (/recaptcha|hcaptcha|g-recaptcha|cf-turnstile/i.test((el.name || '') + ' ' + (el.id || '') + ' ' + (el.className || ''))) continue;
    if (/requiredInput/i.test(el.className || '') && !directLabel(el)) continue;
    if (el.closest('.iti__dropdown-content, .iti__country-container, [class*="iti__search"]')) continue;
    if ((kind === 'checkbox' || kind === 'radio') && el.tagName === 'INPUT' && !isVisible(el) && el.parentElement && el.parentElement.querySelector('button[aria-pressed]')) continue;

    let members = [el];
    if (kind === 'radio' || kind === 'checkbox' || kind === 'toggle') {
      const name = el.getAttribute('name');
      if (name && el.tagName === 'INPUT') {
        members = allControls.filter(c => c.tagName === 'INPUT' && c.getAttribute('name') === name && controlKind(c) === kind);
      } else {
        const grp = el.parentElement ? el.parentElement.closest('[role="radiogroup"], [role="group"], fieldset, .ashby-application-form-input-yesno, [class*="yesno"], [class*="YesNo"], [class*="toggle-group"], [class*="button-group"]') : null;
        if (grp) members = allControls.filter(c => grp.contains(c) && controlKind(c) === kind);
        else if (kind === 'toggle' && el.parentElement) members = allControls.filter(c => c.parentElement === el.parentElement && controlKind(c) === kind);
      }
      members.forEach(m => groupsDone.add(m));
    }

    const fid = nextId();
    const container = fieldContainer(members);
    const optionTexts = (kind === 'radio' || kind === 'checkbox' || kind === 'toggle') ? members.map(optionLabel) : [];
    let label = '';
    let question = '';
    if (members.length > 1 || kind === 'toggle') {
      question = sharedAria(members) || questionFor(members, container, optionTexts);
      label = question;
    } else {
      label = directLabel(el);
      if (!label) {
        label = questionFor(members, container, []) || precedingText(el, root) || clean(el.getAttribute('placeholder')) || clean((el.getAttribute('name') || '').replace(/[_\-\[\]]+/g, ' '));
      } else {
        const fs = el.closest('fieldset');
        const lg = fs ? fs.querySelector('legend') : null;
        const lgt = lg ? ownText(lg) : '';
        const grp = container ? ownText(container, [label]) : '';
        if (lgt && lgt !== label && fs && fieldContainer(members).contains(fs) === false && controlsIn(fs) <= 1) question = lgt;
        else if (grp && grp.length > 3 && grp.length < MAX_LABEL && (kind === 'checkbox' || kind === 'radio' || kind === 'file')) question = grp;
      }
    }
    label = clean(label).slice(0, MAX_LABEL);
    question = clean(question).slice(0, MAX_LABEL);
    const errors = errorsFor(members, container);

    const f = {
      fid, kind,
      label, question,
      section: sectionPath(el, label || question),
      tag: el.tagName.toLowerCase(),
      inputType: (el.getAttribute('type') || '').toLowerCase(),
      role: el.getAttribute('role') || '',
      name: (el.getAttribute('name') || '').slice(0, 120),
      elId: (el.id || '').slice(0, 120),
      autocomplete: el.getAttribute('autocomplete') || '',
      placeholder: clean(el.getAttribute('placeholder')).slice(0, 200),
      required: isRequired(members, label + ' ' + question, container) || errors.some(e => /\brequired\b/i.test(e)),
      errors,
      invalid: members.some(m => m.getAttribute('aria-invalid') === 'true'),
      maxlength: (() => { const v = parseInt(el.getAttribute('maxlength'), 10); return Number.isFinite(v) && v > 0 ? v : null; })(),
      options: [],
      value: '',
      context: container ? ownText(container, []).slice(0, 300) : '',
      visible: isVisible(el)
    };

    if (kind === 'text' || kind === 'date') Object.assign(f, numericInfo(el));
    if (kind === 'text' || kind === 'textarea' || kind === 'date') f.value = el.getAttribute('contenteditable') === 'true' ? clean(el.innerText) : (el.value || '');
    if (kind === 'select') {
      const opts2 = [...el.options].map((o, i) => ({ i, text: clean(o.text), value: o.value, placeholder: (o.value === '' || /^(select|choose|please select|--)/i.test(clean(o.text))) && i === 0 }));
      f.options = opts2.filter(o => o.text).map(o => o.text);
      f.placeholderOption = opts2.length && opts2[0].placeholder ? opts2[0].text : '';
      // unlabeled month/year style selects: the placeholder ("Month", "Year") says what they are
      if (f.placeholderOption && f.placeholderOption.length < 25 && !/select|choose|please|--/i.test(f.placeholderOption) && !(f.label + ' ' + f.question).includes(f.placeholderOption))
        f.label = f.label ? `${f.label} (${f.placeholderOption})` : f.placeholderOption;
      const sel = el.options[el.selectedIndex];
      f.value = sel && !(opts2[el.selectedIndex] && opts2[el.selectedIndex].placeholder) ? clean(sel.text) : '';
      f.multiple = !!el.multiple;
    }
    if (kind === 'combobox') {
      f.value = currentComboValue(el, container);
      f.multiple = !!(container && container.querySelector('[aria-multiselectable="true"], [class*="multi"], [data-automation-id="multiselectInputContainer"]'));
      f.comboVariant = el.tagName === 'BUTTON' ? 'button' : 'input';
      const lbId = el.getAttribute('aria-controls') || el.getAttribute('aria-owns');
      if (lbId) {
        const lb = byId(el, lbId);
        if (lb && isVisible(lb)) f.options = [...lb.querySelectorAll('[role="option"]')].filter(isVisible).map(o => clean(o.innerText)).filter(Boolean).slice(0, 200);
      }
    }
    if (kind === 'radio' || kind === 'checkbox' || kind === 'toggle') {
      f.options = optionTexts.map(t => clean(t).slice(0, 300));
      const checkedOf = m => m.tagName === 'INPUT' ? m.checked : (m.getAttribute('aria-checked') === 'true' || m.getAttribute('aria-pressed') === 'true');
      const checked = members.map((m, i) => checkedOf(m) ? f.options[i] : null).filter(Boolean);
      f.value = checked.join('; ');
      f.single = members.length === 1;
      members.forEach((m, i) => { m.setAttribute('data-lb-fid', fid); m.setAttribute('data-lb-opt', String(i)); });
      // the group's container outlives React re-rendering a clicked option; inputs without a name are re-found inside it
      if (members.length > 1 && container && container !== root) container.setAttribute('data-lb-grp', fid);
    } else {
      el.setAttribute('data-lb-fid', fid);
    }
    if (kind === 'file') {
      f.accept = el.getAttribute('accept') || '';
      f.hasFile = !!(el.files && el.files.length);
      const ctxText = container ? txt(container) : '';
      const m = ctxText.match(/(?:^|\s)([\w\-()]+(?:\.[\w\-()]+)*\.(pdf|docx?|txt|rtf|odt))(?=\s|$)/i);
      f.value = f.hasFile ? 'attached' : (m ? m[1] : '');
    }
    fields.push(f);
  }

  const BTN_SEL = 'button, [role="button"], input[type="submit"], input[type="button"], a[role="button"], a[data-view-name="job-apply-button"], a.button, a.btn, a[class*="apply"]';
  const buttons = [];
  let bn = 0;
  const classify = (t) => {
    const s = t.toLowerCase().trim();
    // social sign-in needs the candidate's own password: never clicked
    if (/^(continue|sign (in|up)|log ?in|register|apply) with (google|microsoft|apple|facebook|github|indeed|seek)\b|^(google|microsoft|apple|facebook|github)$/.test(s)) return 'social';
    if (/^(apply|easy apply|apply now|apply on company website|apply for this (job|position|role)|apply to this (job|position|role)|i'?m interested|apply manually|apply with\b)/.test(s) && !/submit/.test(s)) return 'apply';
    if (/submit|send (my |your )?application|^send( now)?$|^finish( application)?$|^complete (my |your )?application$|confirm and (send|apply)|^complete$/.test(s)) return 'submit';
    if (/\breview\b/.test(s)) return 'review';
    if (/^(next|continue|save (and|&) continue|proceed|save and next|next step|continue to next step|start|start (your |my )?application|begin)\b/.test(s) || /continue to next step/.test(s)) return 'next';
    if (/^(back|previous)\b/.test(s)) return 'back';
    if (/^(dismiss|close|cancel|discard|not now|no thanks|withdraw|delete|remove|sign out|log ?out)\b/.test(s)) return 'close';
    if (/^done\b/.test(s)) return 'done';
    return 'other';
  };
  const scopeForButtons = root === document.body ? document.body : root;
  for (const b of deepAll(scopeForButtons, BTN_SEL)) {
    if (!isVisible(b)) continue;
    if (b.getAttribute('aria-haspopup') === 'listbox' || b.hasAttribute('aria-pressed')) continue;
    const t = clean(b.innerText || b.value || '') || clean(b.getAttribute('aria-label'));
    const aria = clean(b.getAttribute('aria-label'));
    if (!t && !aria) continue;
    const label = t || aria;
    let kind = classify(label);
    if (kind === 'other' && aria) kind = classify(aria);
    if (kind === 'other' && /^(easy apply|apply)/i.test(aria)) kind = 'apply';
    if (kind === 'apply' && (b.getAttribute('type') || '').toLowerCase() === 'submit') {
      const form = b.closest('form');
      if (form && allControls.filter(c => form.contains(c)).length >= 2) kind = 'submit';
    }
    const bid = `b${bn++}`;
    b.setAttribute('data-lb-bid', bid);
    buttons.push({
      bid, text: label.slice(0, 120), aria: aria.slice(0, 160), kind,
      disabled: !!(b.disabled || b.getAttribute('aria-disabled') === 'true'),
      type: (b.getAttribute('type') || '').toLowerCase(),
      href: b.tagName === 'A' ? (b.getAttribute('href') || '') : ''
    });
  }

  const globalErrors = new Set();
  deepAll(root, '[role="alert"], .artdeco-inline-feedback--error, [data-test-form-element-error-messages], [class*="error-message"], [class*="errorMessage"], [data-automation-id="errorMessage"]').forEach(n => {
    if (!isVisible(n)) return;
    const t = clean(n.innerText);
    if (t && t.length < 300) globalErrors.add(t);
  });

  const rootText = clean(root.innerText || '').slice(0, 4000);
  const bodyText = clean(document.body.innerText || '').slice(0, 6000);
  const successRe = /(application (was )?sent|application submitted|your application (was|has been) (sent|submitted|received)|thank(s| you) for (applying|your application|submitting)|we('|’)ve received your application|application received|successfully applied|you('|’)ve applied|application complete)/i;

  let captcha = false;
  deepAll(document, 'iframe').forEach(fr => {
    const src = fr.getAttribute('src') || '';
    if (/recaptcha\/api2\/bframe|recaptcha\/enterprise\/bframe|hcaptcha\.com.*(challenge|hcaptcha-challenge)|challenges\.cloudflare\.com|arkoselabs|funcaptcha/i.test(src)) {
      const r = fr.getBoundingClientRect();
      if (r.width > 100 && r.height > 100 && isVisible(fr)) captcha = true;
    }
  });
  if (/verify (that )?you('| a)re (a )?human|are you a robot|security check|press (and|&) hold/i.test(bodyText.slice(0, 1500))) captcha = true;

  let progress = null;
  const pb = deepAll(root, '[role="progressbar"], progress')[0];
  if (pb) progress = pb.getAttribute('aria-valuenow') || pb.getAttribute('value');
  if (!progress) { const m = rootText.match(/(\d{1,3})\s?(%|percent)/i); if (m) progress = m[1]; }

  const headings = deepAll(root, 'h1, h2, h3, [role="heading"]').filter(isVisible).map(h => clean(h.innerText)).filter(Boolean).slice(0, 6);

  return {
    url: location.href,
    title: document.title,
    rootTag: root === document.body ? 'body' : (root.getAttribute('role') || root.tagName.toLowerCase()),
    fields, buttons,
    errors: [...globalErrors].slice(0, 10),
    headings, progress,
    success: successRe.test(rootText) || successRe.test(bodyText.slice(0, 2500)),
    captcha,
    rootText: rootText.slice(0, 1500)
  };
}
