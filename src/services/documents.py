import re
from datetime import date
from pathlib import Path
from typing import Optional

from src.config import settings
from src.utils.logger import custom_print


def file_purpose(text: str) -> str:
    t = (text or "").lower()
    if re.search(r"cover\s*letter|covering letter|motivation letter|letter of (interest|motivation)", t):
        return "cover_letter"
    if re.search(r"resume|résumé|\bcv\b|curriculum", t):
        return "cv"
    if re.search(r"portfolio|work sample|transcript|certificate|right to work|passport|visa|licen[cs]e|id document|photo|video|reference", t):
        return "other"
    return "unknown"


def safe_name(s: str) -> str:
    return re.sub(r"[^\w\-]+", "_", s or "").strip("_")[:60] or "job"


def cv_path(lane: Optional[str]) -> Optional[Path]:
    p = settings.cv_for_lane(lane)
    if not p:
        custom_print("WARNING", f"No CV file found for lane '{lane}' - check CV_FILES in config.py")
    return p


_CV_TEXT_CACHE = {}


def cv_text(lane: Optional[str]) -> str:
    p = settings.cv_for_lane(lane)
    if not p:
        return ""
    if str(p) in _CV_TEXT_CACHE:
        return _CV_TEXT_CACHE[str(p)]
    text = ""
    try:
        if p.suffix.lower() == ".docx":
            from docx import Document
            d = Document(str(p))
            parts = [para.text for para in d.paragraphs if para.text.strip()]
            for t in d.tables:
                for row in t.rows:
                    parts.append(" | ".join(c.text.strip() for c in row.cells if c.text.strip()))
            text = "\n".join(parts)
        elif p.suffix.lower() == ".pdf":
            from pypdf import PdfReader
            text = "\n".join(pg.extract_text() or "" for pg in PdfReader(str(p)).pages)
        elif p.suffix.lower() in (".txt", ".md"):
            text = p.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        custom_print("WARNING", f"Could not read CV text from {p.name}: {e}")
    _CV_TEXT_CACHE[str(p)] = text
    return text


def write_cover_letter(job: dict, text: str) -> Optional[Path]:
    settings.COVER_LETTER_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"Simon_Che_de_Boer_Cover_Letter_{safe_name(job.get('company', ''))}_{safe_name(str(job.get('linkedin_job_id') or job.get('id') or ''))}"
    try:
        from docx import Document
        from docx.shared import Pt
        doc = Document()
        style = doc.styles["Normal"]
        style.font.name = "Calibri"
        style.font.size = Pt(11)
        doc.add_paragraph(date.today().strftime("%d %B %Y"))
        for para in [p.strip() for p in text.split("\n") if p.strip()]:
            doc.add_paragraph(para)
        out = settings.COVER_LETTER_DIR / f"{stem}.docx"
        doc.save(str(out))
        return out
    except ImportError:
        out = settings.COVER_LETTER_DIR / f"{stem}.txt"
        out.write_text(text, encoding="utf-8")
        custom_print("WARNING", "python-docx not installed - wrote cover letter as .txt (pip install python-docx)")
        return out
