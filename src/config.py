"""
Configuration settings for LinkedIn Boss v2.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # ── AI models (first available in each chain is used; run `python src/main.py doctor` to verify) ──
    MODELS = {
        "eval": ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-2.5-flash"],
        "forms": ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-2.5-flash"],
        "pro": ["gemini-3.1-pro-preview", "gemini-2.5-pro", "gemini-3.8-flash"],
        "lite": ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-2.5-flash-lite"],
        "vision": ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-2.5-flash"],
    }
    GEMINI_MODEL_FORMS = "forms"
    GEMINI_MODEL_COVER = "pro"
    GEMINI_MODEL_EVAL = "eval"
    GEMINI_TEMPERATURE = 0.3
    GEMINI_MAX_TOKENS = 8192

    # ── AI cost controls (same approach as deepPBR) ──
    THINKING_LEVEL = {"eval": "low", "forms": "low", "pro": "low", "lite": "low", "vision": "low"}  # minimal | low | medium | high
    AI_RESULT_CACHE = True              # identical request (models + prompt + schema) is answered from the database, no API call
    AI_CACHE_EPOCH = "1"                # bump to make every older cached answer unreachable
    AI_CACHE_RETENTION_DAYS = 30
    AI_CACHE_MAX_ENTRIES = 5000
    AI_EXPLICIT_CACHE = True            # keep each stable system prompt (instructions + CV) in a Gemini context cache
    AI_EXPLICIT_CACHE_MIN_TOKENS = 1024 # smaller prompts rely on Gemini's automatic (implicit) prefix cache
    AI_EXPLICIT_CACHE_TTL_SECONDS = 3600

    # ── Approval / run modes ──
    MANUAL_APPROVAL = True
    DRY_RUN = False
    DEFAULT_COMMAND = "run"

    # ── Rate limiting ──
    MAX_APPLICATIONS_PER_DAY = 40
    MIN_DELAY_BETWEEN_APPS = 240
    MAX_DELAY_BETWEEN_APPS = 480
    JOB_READ_TIME_MIN = 120
    JOB_READ_TIME_MAX = 240
    EXTERNAL_READ_TIME_MIN = 20
    EXTERNAL_READ_TIME_MAX = 60

    # ── Browser ──
    HEADLESS = False
    SLOW_MO = 50
    VIEWPORT = {"width": 1920, "height": 1080}
    BROWSER_CHANNEL = "chrome"          # "chrome" = installed Google Chrome (less detectable); None = bundled Chromium
    HUMAN_TYPING = True

    # ── Scraping ──
    MAX_JOBS_TO_SCRAPE = 150
    SCROLL_PAUSE_TIME = 4
    MAX_PAGES_PER_SEARCH = 2
    MAX_SEARCHES_PER_RUN = 24
    SEARCH_DATE_FILTER = "r2592000"     # r86400 = 24h, r604800 = week, r2592000 = month (backlog; newest are applied to first)
    EASY_APPLY_ONLY = False             # False = scrape everything; external applications go through the ATS appliers
    SEARCH_SORT = "DD"                  # DD = newest first, R = relevance
    JOB_TYPES = "F,C,T"                 # F full-time, C contract, T temporary, P part-time

    # location key -> (LinkedIn geoId, workplace filter: None | "1" onsite | "2" remote | "3" hybrid | "1,2,3")
    SEARCH_LOCATIONS = {
        "New Zealand": ("105490917", None),
        "Sydney": ("104769905", None),
        "Melbourne": ("100992797", None),
        "Australia (remote)": ("101452733", "2"),
        "Australia": ("101452733", None),
        "Worldwide (remote)": ("92000000", "2"),
    }

    SEARCH_LANES = {
        "fde": [
            "forward deployed engineer",
            "ai deployment engineer",
            "solutions engineer ai",
            "applied ai engineer",
            "customer engineer ai",
        ],
        "applied_ai": [
            "ai engineer",
            "llm engineer",
            "generative ai engineer",
            "machine learning engineer",
            "ai architect",
            "ai product engineer",
            "conversational ai engineer",
        ],
        "graphics_3d_cv": [
            "graphics engineer",
            "computer vision engineer",
            "3d engineer",
            "rendering engineer",
            "xr engineer",
            "creative technologist",
            "photogrammetry",
            "unreal engine developer",
            "technical director",
            "vfx pipeline",
            "virtual production",
            "immersive technology",
            "real-time 3d",
        ],
        "audio_media": [
            "audio software engineer",
            "audio ai",
            "dsp engineer",
            "music technology",
            "media technology",
        ],
        "platform_arch": [
            "solutions architect",
            "platform architect",
            "technical architect",
            "senior platform engineer",
            "senior backend engineer",
            "python developer",
            "senior software engineer",
            "staff engineer",
            "principal engineer",
        ],
        "leadership": [
            "head of engineering",
            "engineering manager",
            "technical lead",
            "lead engineer",
            "cto",
            "head of ai",
            "director of engineering",
            "founding engineer",
            "ai consultant",
        ],
    }

    # ── Evaluation ──
    CONFIDENCE_THRESHOLD = 50           # volume strategy: apply wherever there's a realistic shot
    GEMINI_MAX_RETRIES = 3
    USE_PREFILTER = True
    PREFILTER_BATCH_SIZE = 100
    REPOST_COOLDOWN_DAYS = 45           # skip same company + same title if applied within this window
    SORT_QUEUE_BY_PAY = True
    QUEUE_MAX_AGE_DAYS = 21             # approved jobs older than this are ignored (listings go stale)
    FX_TO_NZD = {"NZD": 1.0, "AUD": 1.10, "USD": 1.72, "EUR": 1.90, "GBP": 2.22, "SGD": 1.30, "CAD": 1.24}
    WORK_DAYS_PER_YEAR = 220
    WORK_HOURS_PER_YEAR = 1760

    # ── Applying ──
    ENABLE_VALIDATION_RETRY = True
    MAX_VALIDATION_RETRIES = 1
    RETRY_MAX_AGE_DAYS = 14
    MAX_FORM_STEPS = 25
    EXTERNAL_APPLY = True
    # auto-submit allowed per application system when MANUAL_APPROVAL is off; others stop for you before submit
    EXTERNAL_AUTO_SUBMIT = {
        "greenhouse": True, "lever": True, "ashby": True, "workable": True, "smartrecruiters": True,
        "jobadder": True, "recruitee": True, "teamtailor": True, "breezy": True, "bamboohr": True,
        "workday": True, "seek": True, "pageup": True, "icims": True, "successfactors": True,
        "taleo": True, "jobvite": True, "generic": True,
    }
    VISION_ASSIST = True                # screenshot + Gemini picks the next step when the DOM loop gets stuck
    EEO_POLICY = "decline"              # voluntary diversity questions: "decline" picks prefer-not-to-say options
    FILL_OPTIONAL_LONGFORM = False      # optional essay boxes (other than cover letters) left blank
    GENERATE_COVER_LETTERS = True       # write a tailored letter when a cover letter field/upload exists
    ANSWER_BANK_REUSE_PENDING = True    # reuse AI answers you haven't reviewed yet (tagged 'saved-unreviewed' in summaries)
    MENTION_APPLICATION_BOT = False     # False = cover letters/answers never mention this bot (cv_data meta_automation is withheld)

    CV_FILES = {
        "default": "Data/Simon_Che_de_Boer_CV_AIPlatform.docx",
        "applied_ai": "Data/Simon_Che_de_Boer_CV_AIPlatform.docx",
        "fde": "Data/Simon_Che_de_Boer_CV_AIPlatform.docx",
        "platform_arch": "Data/Simon_Che_de_Boer_CV_MLOps.docx",
        "leadership": "Data/Simon_Che_de_Boer_CV_AIPlatform.docx",
        "graphics_3d_cv": "Data/Simon_Che_de_Boer_CV_AIPlatform.docx",
    }

    # ── Interview Assistant ──
    INTERVIEW_SENTINEL_MODEL = "gemini-2.5-flash-lite"
    INTERVIEW_SENTINEL_MAX_TOKENS = 200
    INTERVIEW_ADVISOR_MODEL = "gemini-2.5-flash-lite"
    INTERVIEW_ADVISOR_MAX_TOKENS = 4096
    INTERVIEW_SAMPLE_RATE = 16000
    INTERVIEW_CHUNK_DURATION = 3
    INTERVIEW_SILENCE_THRESHOLD = 0.01
    INTERVIEW_WHISPER_MODEL = "large-v3"
    INTERVIEW_WHISPER_DEVICE = "cuda"
    INTERVIEW_WHISPER_COMPUTE_TYPE = "float16"
    INTERVIEW_DISPLAY_FONT_SIZE = 72
    INTERVIEW_DISPLAY_BG = "#000000"
    INTERVIEW_DISPLAY_FG = "#FFFF00"
    INTERVIEW_DISPLAY_WIDTH = 1400
    INTERVIEW_DISPLAY_HEIGHT = 500

    # ── Paths ──
    BASE_DIR = Path(__file__).parent.parent
    DATA_DIR = BASE_DIR / "data"
    DB_PATH = str(DATA_DIR / "applications.db")
    SESSION_PATH = str(DATA_DIR / "linkedin_session.json")
    PROFILE_DIR = DATA_DIR / "browser_profile"
    LOGS_DIR = DATA_DIR / "logs"
    DEBUG_DIR = DATA_DIR / "debug_html"
    FIXTURE_DIR = DATA_DIR / "fixtures"
    COVER_LETTER_DIR = DATA_DIR / "cover_letters"
    KEYS_DIR = BASE_DIR / "src" / "keys"

    @staticmethod
    def load_api_key_from_file(key_name: str) -> str | None:
        env_var = key_name.upper()
        value = os.environ.get(env_var) or os.environ.get("GEMINI_API_KEY")
        if value:
            return value.strip()
        key_file = settings.KEYS_DIR / f"{key_name}.txt"
        if key_file.exists():
            return key_file.read_text().strip()
        return None

    @staticmethod
    def env(name: str, default: str = None) -> str | None:
        v = os.environ.get(name)
        return v.strip() if v else default

    @staticmethod
    def all_keywords() -> list:
        out = []
        for lane, kws in settings.SEARCH_LANES.items():
            out += [(lane, k) for k in kws]
        return out

    @staticmethod
    def build_search_url(location_key: str, keyword: str, start: int = 0) -> str:
        geo, workplace = settings.SEARCH_LOCATIONS[location_key]
        params = [
            f"keywords={keyword.replace(' ', '%20')}",
            f"geoId={geo}",
            f"f_TPR={settings.SEARCH_DATE_FILTER}",
            f"sortBy={settings.SEARCH_SORT}",
        ]
        if settings.EASY_APPLY_ONLY:
            params.append("f_AL=true")
        if workplace:
            params.append(f"f_WT={workplace.replace(',', '%2C')}")
        if settings.JOB_TYPES:
            params.append(f"f_JT={settings.JOB_TYPES.replace(',', '%2C')}")
        if start:
            params.append(f"start={start}")
        return "https://www.linkedin.com/jobs/search/?" + "&".join(params)

    @staticmethod
    def cv_for_lane(lane: str | None) -> Path | None:
        rel = settings.CV_FILES.get(lane or "default") or settings.CV_FILES.get("default")
        if not rel:
            return None
        p = Path(rel)
        if not p.is_absolute():
            p = settings.BASE_DIR / rel
        if p.exists():
            return p
        alt = settings.BASE_DIR / rel.replace("Data/", "data/")
        return alt if alt.exists() else None

    @staticmethod
    def ensure_directories():
        for d in (settings.DATA_DIR, settings.LOGS_DIR, settings.KEYS_DIR, settings.DEBUG_DIR,
                  settings.FIXTURE_DIR, settings.COVER_LETTER_DIR, settings.PROFILE_DIR):
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_directories()
