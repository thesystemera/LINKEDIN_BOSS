"""
Configuration settings for LinkedIn Auto-Apply system.
"""
from pathlib import Path

class Settings:
    GEMINI_MODEL_FORMS = "gemini-2.5-flash"      # Fast model for form fields
    GEMINI_MODEL_COVER = "gemini-2.5-pro"        # Best model for cover letters
    GEMINI_MODEL_EVAL = "gemini-2.5-flash"       # Job evaluation
    GEMINI_TEMPERATURE = 0.3
    GEMINI_MAX_TOKENS = 8192

    # Manual Approval Settings
    MANUAL_APPROVAL = True  # Require confirmation before each submit
    DRY_RUN = False         # If True, stops before clicking submit (just shows what it would do)

    # IDE Default Behavior (when running with "play button")
    DEFAULT_COMMAND = "run"  # Default: run, setup, stats, review

    # Rate Limiting (Aggressive but human-like)
    MAX_APPLICATIONS_PER_DAY = 80       # ~15 apps/hour for 5 hour session
    MIN_DELAY_BETWEEN_APPS = 30         # 30 seconds (seconds)
    MAX_DELAY_BETWEEN_APPS = 120           # 2 minutes (seconds)
    # Average delay: ~4 minutes = 15 apps/hour (human-plausible)
    JOB_READ_TIME_MIN = 30  # Seconds to "read" job description
    JOB_READ_TIME_MAX = 120

    # Job Scraping
    MAX_JOBS_TO_SCRAPE = 100
    SCROLL_PAUSE_TIME = 2

    USE_SEARCH_MODE = True
    # SEARCH_LOCATIONS = ["New Zealand", "Melbourne", "Sydney", "China", "Singapore", "Hong Kong"]
    SEARCH_LOCATIONS = ["New Zealand", "Melbourne", "Sydney"]
    SEARCH_DATE_FILTER = "r604800"

    SEARCH_KEYWORDS = [
        # Primary targets
        "solutions architect",
        "technical architect",
        "platform architect",
        "principal architect",
        "staff architect",

        # Technical leadership
        "technical lead",
        "engineering lead",
        "head of engineering",

        # Domain-specific architect roles
        "ai architect",
        "ml architect",

        # Creative/visual (your differentiator)
        "xr architect",
        "graphics architect",
        "creative technologist",
        "computer vision engineer",
        "vfx technical director",

        # Fallback senior roles (architecture-focused)
        "senior platform engineer",
        "staff engineer",
        "principal engineer",
    ]

    # Gemini Evaluation
    CONFIDENCE_THRESHOLD = 60
    GEMINI_MAX_RETRIES = 3

    USE_PREFILTER = True
    PREFILTER_BATCH_SIZE = 100

    # Form Validation Retry Settings
    ENABLE_VALIDATION_RETRY = True  # Enable AI retry when validation fails
    MAX_VALIDATION_RETRIES = 1      # Max retries per form page (1 = one retry, total 2 attempts)

    # Retry Settings
    RETRY_MAX_AGE_DAYS = 14         # Only retry jobs scraped within this many days

    # Interview Assistant Settings (Two-Tier Architecture)
    # Tier 1: Sentinel - lightweight, fires every chunk, detects questions/answers
    INTERVIEW_SENTINEL_MODEL = "gemini-2.5-flash-lite"  # $0.10/1M input - cheapest 2.5 model
    INTERVIEW_SENTINEL_MAX_TOKENS = 200  # Just needs "QUESTION: text" or "WAITING"
    # Tier 2: Advisor - full context, fires only when Sentinel detects something
    INTERVIEW_ADVISOR_MODEL = "gemini-2.5-flash-lite"  # Testing if flash-lite is faster
    INTERVIEW_ADVISOR_MAX_TOKENS = 4096

    # Audio settings
    INTERVIEW_SAMPLE_RATE = 16000        # Whisper expects 16kHz
    INTERVIEW_CHUNK_DURATION = 3         # Seconds per transcription chunk
    INTERVIEW_SILENCE_THRESHOLD = 0.01   # VAD threshold
    INTERVIEW_WHISPER_MODEL = "large-v3"  # Best quality - faster-whisper optimizes with CTranslate2
    INTERVIEW_WHISPER_DEVICE = "cuda"    # "cuda" or "cpu"
    INTERVIEW_WHISPER_COMPUTE_TYPE = "float16"  # "float16" for GPU, "int8" for CPU

    # Display settings (high contrast for low vision)
    INTERVIEW_DISPLAY_FONT_SIZE = 72     # Reduced for less glare
    INTERVIEW_DISPLAY_BG = "#000000"     # Black background
    INTERVIEW_DISPLAY_FG = "#FFFF00"     # Yellow text
    INTERVIEW_DISPLAY_WIDTH = 1400
    INTERVIEW_DISPLAY_HEIGHT = 500

    # Browser Configuration
    HEADLESS = False  # MUST be False to avoid detection
    SLOW_MO = 50  # Milliseconds between Playwright actions
    VIEWPORT = {"width": 1920, "height": 1080}

    # LinkedIn Selectors (adjust if LinkedIn changes their HTML - updated Jan 2026)
    SELECTORS = {
        "easy_apply_button": '[data-view-name="job-apply-button"], [aria-label*="Easy Apply"], .jobs-apply-button',
        "next_button": 'button[aria-label*="Continue"], button:has-text("Next")',
        "submit_button": 'button[aria-label*="Submit application"]',
        "review_button": 'button[aria-label*="Review"]',
        "close_button": 'button[aria-label*="Dismiss"]',
    }

    BASE_DIR = Path(__file__).parent.parent
    DATA_DIR = BASE_DIR / "data"
    DB_PATH = str(DATA_DIR / "applications.db")
    SESSION_PATH = str(DATA_DIR / "linkedin_session.json")
    LOGS_DIR = DATA_DIR / "logs"
    KEYS_DIR = BASE_DIR / "src" / "keys"

    @staticmethod
    def load_api_key_from_file(key_name: str) -> str | None:
        key_file = Settings.KEYS_DIR / f"{key_name}.txt"
        if key_file.exists():
            with open(key_file, 'r') as f:
                return f.read().strip()
        return None

    @staticmethod
    def get_geo_id(location: str) -> str:
        """Get LinkedIn geoId for a location"""
        geo_ids = {
            "New Zealand": "105490917",
            "Melbourne": "100992797",
            "Sydney": "104769905",
            # "Shanghai": "102772228",
            # "Shenzhen": "106750182",
            # "Beijing": "103873152",
            # "Singapore": "102454443",
            # "Hong Kong": "103291313",
            # "China": "102890883",
        }
        return geo_ids.get(location, "105490917")

    @staticmethod
    def build_search_url(location: str = None, keyword: str = None) -> str:
        """Build LinkedIn search URL with filters for a single keyword"""
        if location is None:
            location = Settings.SEARCH_LOCATIONS[0]

        geo_id = Settings.get_geo_id(location)

        url = f"https://www.linkedin.com/jobs/search/?f_AL=true&f_TPR={Settings.SEARCH_DATE_FILTER}&geoId={geo_id}"

        if keyword:
            encoded_keyword = keyword.replace(" ", "%20")
            url += f"&keywords={encoded_keyword}"

        url += "&sortBy=R"
        return url

    @staticmethod
    def ensure_directories():
        """Create necessary directories if they don't exist"""
        Settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
        Settings.LOGS_DIR.mkdir(parents=True, exist_ok=True)
        Settings.KEYS_DIR.mkdir(parents=True, exist_ok=True)

settings = Settings()

settings.ensure_directories()