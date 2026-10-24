import re
import difflib
from typing import List, Optional, Tuple

DECLINE_RE = re.compile(r"(decline|prefer not|don'?t wish|do not wish|not wish to|not to (say|disclose|answer|identify)|rather not|choose not|i don'?t want|no answer|not specified)", re.I)
# answers that mean "decline" (narrower than DECLINE_RE, which also has to recognise the many option wordings)
DECLINE_ANSWER_RE = re.compile(r"\b(decline|prefer not|choose not|rather not|(do not|don'?t) wish|not to (say|disclose|answer|identify))\b", re.I)

YES = {"yes", "y", "true", "1", "agree", "i agree", "accept", "i accept", "confirm", "i confirm", "checked", "consent", "i consent"}
NO = {"no", "n", "false", "0", "disagree", "decline", "unchecked"}


def norm(s) -> str:
    s = str(s or "").lower().replace("&", " and ")
    s = re.sub(r"[‘’“”]", "'", s)
    s = re.sub(r"[^\w\s+$%.,/'-]", " ", s)
    s = re.sub(r"(?<=\d),(?=\d{3})", "", s)
    s = re.sub(r"[\s,.;:/'-]+", " ", s)
    return s.strip()


def truthy(answer) -> Optional[bool]:
    if isinstance(answer, bool):
        return answer
    a = norm(answer)
    if not a:
        return None
    if a in YES or a.startswith("yes"):
        return True
    if a in NO or a.startswith("no "):
        return False
    return None


def parse_amount(text) -> Optional[float]:
    t = str(text or "").lower().replace(",", "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*(k|m)?\b", t)
    if not m:
        return None
    v = float(m.group(1))
    if m.group(2) == "k":
        v *= 1_000
    elif m.group(2) == "m":
        v *= 1_000_000
    return v


def option_range(opt: str) -> Optional[Tuple[float, float]]:
    t = opt.lower().replace(",", "")
    nums = []
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(k|m)?(?![\d])", t):
        v = float(m.group(1))
        if m.group(2) == "k":
            v *= 1_000
        elif m.group(2) == "m":
            v *= 1_000_000
        nums.append(v)
    if not nums:
        return None
    if len(nums) >= 2:
        return (min(nums[0], nums[1]), max(nums[0], nums[1]))
    n = nums[0]
    if re.search(r"\+|more|over|above|greater|at least|or more", t):
        return (n, float("inf"))
    if re.search(r"less|under|below|fewer|up to|<", t):
        return (0.0, n)
    return (n, n)


def _share_word(a: str, o: str) -> bool:
    ow = [w for w in o.split() if len(w) >= 3]
    return any(w == x or (min(len(w), len(x)) >= 4 and (w.startswith(x) or x.startswith(w)))
               for w in a.split() if len(w) >= 3 for x in ow)


def match_option(answer, options: List[str], fuzzy_cutoff: float = 0.6) -> Optional[int]:
    if answer is None or not options:
        return None
    a = norm(answer)
    if not a:
        return None
    normed = [norm(o) for o in options]
    for i, o in enumerate(normed):
        if o == a:
            return i
    # each site words "decline" its own way: "Choose not to disclose", "I don't wish to answer", "Decline to self-identify"
    if DECLINE_ANSWER_RE.search(str(answer)):
        for i, o in enumerate(options):
            if DECLINE_RE.search(o):
                return i
    tv = truthy(answer)
    if tv is not None and a in YES | NO:
        for i, o in enumerate(normed):
            if tv and (o == "yes" or o.startswith("yes ") or o in YES):
                return i
            if not tv and (o == "no" or o.startswith("no ") or o in NO):
                return i
    for i, o in enumerate(normed):
        if len(a) >= 2 and (o.startswith(a + " ") or a.startswith(o + " ")) and len(o) >= 2:
            return i
    for i, o in enumerate(normed):
        if len(a) > 3 and len(o) > 3 and (a in o or o in a):
            return i
    val = parse_amount(answer)
    if val is not None and re.fullmatch(r"[\s$€£nzdaus]*[\d.,]+\s*(k|m|years?|yrs?|weeks?|months?|days?)?\s*\+?", str(answer).strip().lower()):
        best, best_w = None, None
        for i, o in enumerate(options):
            r = option_range(o)
            if r and r[0] <= val <= r[1]:
                w = r[1] - r[0]
                if best is None or w < best_w:
                    best, best_w = i, w
        if best is not None:
            return best
    scores = [difflib.SequenceMatcher(None, a, o).ratio() for o in normed]
    i = max(range(len(scores)), key=lambda k: scores[k])
    # a loose match also needs a word in common: "new zealand" and "netherlands" score 0.64 on letters alone
    if scores[i] >= 0.85 or (scores[i] >= fuzzy_cutoff and _share_word(a, normed[i])):
        return i
    at = set(a.split())
    best_j, best_s = None, 0.0
    for j, o in enumerate(normed):
        ot = set(o.split())
        if not ot:
            continue
        s = len(at & ot) / max(1, len(at | ot))
        if s > best_s:
            best_j, best_s = j, s
    if best_s >= 0.5:
        return best_j
    return None


def split_multi(answer) -> List[str]:
    if isinstance(answer, (list, tuple)):
        return [str(x).strip() for x in answer if str(x).strip()]
    parts = re.split(r"\s*(?:;|\n|\|)\s*", str(answer or ""))
    if len(parts) == 1 and "," in parts[0] and len(parts[0]) < 200:
        parts = re.split(r"\s*,\s*", parts[0])
    return [p.strip() for p in parts if p.strip()]
