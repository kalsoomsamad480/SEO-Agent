"""Project settings in one place.

Settings come from two places:
1. Secrets and per-computer values (API keys, model name) come from the .env file.
2. SEO rule numbers and folder paths are plain constants below, so you can
   change them in one spot without touching the rest of the code.

Run `python config.py` to check that your setup is correct.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Find files relative to THIS file, not to wherever you run Python from.
# That way `python main.py` works from any folder.
PROJECT_ROOT = Path(__file__).resolve().parent

# Read .env into environment variables. If .env does not exist, nothing
# happens and the defaults below are used.
load_dotenv(PROJECT_ROOT / ".env")


class ConfigError(Exception):
    """Raised when a required setting (like an API key) is missing."""


# ---------------------------------------------------------------------------
# SEO rules (change these numbers to make the validator stricter or looser)
# ---------------------------------------------------------------------------
MIN_WORDS = 1000
MIN_FOCUS_KEYWORD_COUNT = 5         # focus keyword at least 5 times in the body
MAX_KEYWORD_DENSITY_PERCENT = 2.0   # warn above this (avoid keyword stuffing)
MIN_EXTERNAL_LINKS = 1              # at least 1 link to a high-authority site
MIN_FAQ_QUESTIONS = 3
META_DESCRIPTION_MAX_CHARS = 160
TITLE_MAX_CHARS = 60
MAX_FIX_ROUNDS = 3                  # writer <-> reviewer loop limit
FIRST_WORDS_WINDOW = 100            # focus keyword must appear in the first N words
MIN_H2_HEADINGS = 2                 # a real structure needs at least 2 sections
FAQ_MAX_ANSWER_WORDS = 80           # FAQ answers must be short and direct

# Reading level per audience, measured with the Flesch Reading Ease score
# (0-100, higher = easier). Code can't judge "tone", but it CAN check that
# the text isn't too hard for the people you're writing for.
# The first key found inside your audience text is used, e.g. "small business owners"
# matches "business owners".
AUDIENCE_MIN_READING_EASE = {
    "beginner": 60,
    "kid": 70,
    "student": 50,
    "business owner": 50,
    "general": 50,
    "developer": 30,
    "expert": 30,
}
DEFAULT_MIN_READING_EASE = 50

# Which external sites count as "high authority".
# A link passes if its domain ENDS WITH a suffix or IS (or is under) a domain below.
AUTHORITY_SUFFIXES = (".gov", ".edu", ".int", ".mil", ".gov.uk", ".ac.uk", ".gov.pk", ".edu.pk", ".gov.au", ".edu.au")
AUTHORITY_DOMAINS = (
    "wikipedia.org", "who.int", "w3.org", "developer.mozilla.org", "python.org",
    "developers.google.com", "support.google.com", "learn.microsoft.com", "docs.github.com",
    "nature.com", "sciencedirect.com", "britannica.com", "bbc.co.uk", "bbc.com",
    "reuters.com", "apnews.com", "nytimes.com", "forbes.com", "hbr.org", "statista.com",
    "pewresearch.org", "worldbank.org", "imf.org", "oecd.org",
)

# Anchor text that tells readers (and Google) nothing about the target page.
GENERIC_ANCHOR_TEXTS = ("click here", "here", "read more", "this link", "link", "more", "this")

# ---------------------------------------------------------------------------
# Audit and crawling (be polite to other people's servers)
# ---------------------------------------------------------------------------
DEFAULT_MAX_PAGES = 50
CRAWL_DELAY_SECONDS = 1.0           # wait between requests to the same site
HTTP_TIMEOUT_SECONDS = 15           # for crawling and link checks
USER_AGENT = "SEOAgentBot/0.1 (+educational project)"

# ---------------------------------------------------------------------------
# Folders
# ---------------------------------------------------------------------------
PROMPTS_DIR = PROJECT_ROOT / "prompts"
LOGS_DIR = PROJECT_ROOT / "logs"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
BLOGS_DIR = OUTPUTS_DIR / "blogs"
AUDITS_DIR = OUTPUTS_DIR / "audits"
OUTREACH_DIR = OUTPUTS_DIR / "outreach"
SITE_MAP_FILE = OUTPUTS_DIR / "site_map.json"
TRACKER_FILE = OUTREACH_DIR / "backlink_tracker.csv"

# ---------------------------------------------------------------------------
# Values from .env (empty string means "not set")
# ---------------------------------------------------------------------------
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")
LLM_BASE_URL = os.getenv(
    "LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai"
)
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-flash-latest")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_FALLBACK_MODEL = os.getenv("LLM_FALLBACK_MODEL", "")
LLM_TIMEOUT_SECONDS = int(os.getenv("LLM_TIMEOUT_SECONDS", "120"))

# Your website's address, e.g. https://myblog.com (used to build page URLs and
# internal links). Leave empty to use relative links like /my-post/.
SITE_URL = os.getenv("SITE_URL", "").rstrip("/")

PAGESPEED_API_KEY = os.getenv("PAGESPEED_API_KEY", "")

# Optional: Brave Search API key, used to find backlink opportunities (Phase 7).
BRAVE_SEARCH_API_KEY = os.getenv("BRAVE_SEARCH_API_KEY", "")

WORDPRESS_URL = os.getenv("WORDPRESS_URL", "")
WORDPRESS_USERNAME = os.getenv("WORDPRESS_USERNAME", "")
WORDPRESS_APP_PASSWORD = os.getenv("WORDPRESS_APP_PASSWORD", "")

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()


def ensure_folders() -> None:
    """Create the output and log folders if they don't exist yet.

    These folders are git-ignored, so a fresh copy of the project
    won't have them. Creating them here saves you from "folder not found" errors.
    """
    for folder in (LOGS_DIR, BLOGS_DIR, AUDITS_DIR, OUTREACH_DIR):
        folder.mkdir(parents=True, exist_ok=True)


def require_setting(name: str) -> str:
    """Return a setting from .env, or raise a friendly ConfigError if it is empty.

    Use this only at the moment a feature actually needs the key, so that
    e.g. the validator still works even if you have no LLM key yet.
    """
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigError(
            f"The setting '{name}' is missing. "
            f"Copy .env.example to .env and fill in {name}."
        )
    return value


def _mask(secret: str) -> str:
    """Show only the last 4 characters of a secret so it is safe to print."""
    if not secret:
        return "(not set)"
    return "****" + secret[-4:]


def print_setup_check() -> None:
    """Print a short report of the current settings (secrets masked)."""
    env_file = PROJECT_ROOT / ".env"
    print("SEO Agent - setup check")
    print("-" * 40)
    print(f".env file found     : {'yes' if env_file.exists() else 'NO (copy .env.example to .env)'}")
    print(f"LLM provider        : {LLM_PROVIDER}")
    print(f"LLM model           : {LLM_MODEL}")
    print(f"LLM API key         : {_mask(LLM_API_KEY)}")
    print(f"PageSpeed API key   : {_mask(PAGESPEED_API_KEY)} (optional)")
    print(f"Min words / FAQ     : {MIN_WORDS} / {MIN_FAQ_QUESTIONS}")
    print(f"Outputs folder      : {OUTPUTS_DIR}")
    print(f"Log file            : {LOGS_DIR / 'app.log'}")


# Make sure the folders exist as soon as any module imports config.
ensure_folders()

if __name__ == "__main__":
    print_setup_check()
