"""Find high-authority external sources to link to, and VERIFY them.

LLMs sometimes invent URLs that look real but don't exist. So every
candidate must pass three checks in code before we use it:
    1. The domain is high-authority (.gov, .edu, trusted list in config).
    2. The page responds with HTTP 200.
    3. The page actually mentions the topic.

Candidates come from the LLM's suggestions first, then a Wikipedia search
(free API, no key), which almost always finds something real.
"""

import re

import requests

import config
from src.utils import text_tools as tt
from src.utils.logger import get_logger
from src.validators.seo_rules import is_authority_domain

logger = get_logger(__name__)

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
MAX_LINKS = 2


def fetch_page(url: str) -> tuple[int | None, str]:
    """Download a page: return (status code, lower-case text). (None, "") if unreachable."""
    try:
        response = requests.get(url, headers={"User-Agent": config.USER_AGENT},
                                timeout=config.HTTP_TIMEOUT_SECONDS, allow_redirects=True)
        return response.status_code, response.text[:300_000].lower()
    except requests.RequestException as error:
        logger.debug("Could not fetch %s (%s)", url, type(error).__name__)
        return None, ""


def mentions_topic(page_text: str, keyword: str) -> bool:
    """True if at least half of the keyword's meaningful words appear on the page.

    Short words like "a", "to", "for" are ignored because every page has them.
    """
    words = [w for w in re.findall(r"\w+", keyword.lower()) if len(w) > 3]
    if not words:
        return True
    found = sum(1 for w in words if w in page_text)
    return found >= len(words) / 2


def verify_source(url: str, keyword: str) -> bool:
    """Run all three checks on one candidate URL."""
    if not is_authority_domain(tt.get_domain(url)):
        logger.info("  Rejected (not a high-authority site): %s", url)
        return False
    status, text = fetch_page(url)
    if status != 200:
        logger.info("  Rejected (HTTP %s): %s", status or "unreachable", url)
        return False
    if not mentions_topic(text, keyword):
        logger.info("  Rejected (page doesn't match the topic): %s", url)
        return False
    logger.info("  Verified: %s", url)
    return True


def search_wikipedia(query: str, limit: int = 3) -> list[str]:
    """Search Wikipedia and return article URLs (empty list on any error)."""
    params = {"action": "query", "list": "search", "srsearch": query,
              "srlimit": limit, "format": "json"}
    try:
        response = requests.get(WIKIPEDIA_API, params=params,
                                headers={"User-Agent": config.USER_AGENT},
                                timeout=config.HTTP_TIMEOUT_SECONDS)
        response.raise_for_status()
        results = response.json()["query"]["search"]
    except (requests.RequestException, ValueError, KeyError) as error:
        logger.warning("Wikipedia search failed (%s)", type(error).__name__)
        return []
    return [f"https://en.wikipedia.org/wiki/{r['title'].replace(' ', '_')}" for r in results]


def find_authority_links(keyword: str, suggestions: list[str], topic: str = "",
                         max_links: int = MAX_LINKS) -> list[str]:
    """Return up to `max_links` verified high-authority URLs for the keyword."""
    logger.info("Verifying authority sources for '%s'...", keyword)
    candidates = list(suggestions) + search_wikipedia(keyword)
    if topic and topic.lower() != keyword.lower():
        candidates += search_wikipedia(topic)

    verified: list[str] = []
    for url in dict.fromkeys(candidates):   # dict.fromkeys removes duplicates, keeps order
        if len(verified) >= max_links:
            break
        if verify_source(url, keyword):
            verified.append(url)

    if not verified:
        logger.warning("No verified authority source found. The SEO check will flag this; "
                       "add a trusted link by hand before publishing.")
    return verified
