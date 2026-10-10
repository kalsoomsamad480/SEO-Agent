"""Auto mode: find what people are searching for in your niche.

Two free sources:
1. Google Trends via pytrends (top + rising related searches). pytrends is
   unofficial, so Google sometimes blocks it. When that happens we fall back to:
2. Google autocomplete: the suggestions you see while typing in Google.
   These are real searches people make.

Topics are then ranked by relevance to your niche, in plain code.
"""

import re
import time

import requests

import config
from src.models.schemas import TopicIdea
from src.utils.logger import get_logger

logger = get_logger(__name__)

AUTOCOMPLETE_URL = "https://suggestqueries.google.com/complete/search"
# Words we put around the niche to discover more autocomplete ideas.
TOPIC_PATTERNS = ["{niche}", "how to {niche}", "best {niche}", "{niche} for beginners",
                  "{niche} vs", "what is {niche}"]
SMALL_PAUSE_SECONDS = 0.5     # be polite: don't fire requests back-to-back
LOOKS_LIKE_WEBSITE = re.compile(r"\w\.(com|org|net|io|co|in|pk|xyz)\b", re.IGNORECASE)


class ResearchError(Exception):
    """Research could not find what it needed (e.g. no topics, no internet)."""


def google_autocomplete(query: str) -> list[str]:
    """Return Google's autocomplete suggestions for a query (empty list on any error)."""
    try:
        response = requests.get(
            AUTOCOMPLETE_URL,
            params={"client": "firefox", "q": query, "hl": "en"},
            headers={"User-Agent": config.USER_AGENT},
            timeout=config.HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        # The reply looks like: ["the query", ["suggestion 1", "suggestion 2", ...], ...]
        return [s for s in response.json()[1] if isinstance(s, str)]
    except (requests.RequestException, ValueError, IndexError) as error:
        logger.warning("Autocomplete failed for '%s' (%s)", query, type(error).__name__)
        return []


def fetch_google_trends(niche: str) -> list[TopicIdea]:
    """Ask Google Trends for searches related to the niche. Raises on any failure."""
    from pytrends.request import TrendReq   # imported here: it's slow to load and only needed here

    trends = TrendReq(hl="en-US", tz=0, timeout=(10, 25))
    trends.build_payload([niche], timeframe="today 3-m")
    related = trends.related_queries().get(niche) or {}
    ideas = []
    for kind in ("rising", "top"):   # rising = growing fast right now
        table = related.get(kind)
        if table is not None:
            ideas += [TopicIdea(topic=q, source=f"google trends ({kind})") for q in table["query"]]
    return ideas


def fetch_autocomplete_topics(niche: str) -> list[TopicIdea]:
    """Collect autocomplete suggestions for the niche with a few common patterns."""
    ideas = []
    for pattern in TOPIC_PATTERNS:
        for suggestion in google_autocomplete(pattern.format(niche=niche)):
            ideas.append(TopicIdea(topic=suggestion, source="google autocomplete"))
        time.sleep(SMALL_PAUSE_SECONDS)
    return ideas


def relevance_score(topic: str, niche: str) -> float:
    """Share of the niche's words that appear in the topic (0.0 to 1.0).

    "web development course" for niche "web development" -> 1.0
    "web hosting" for niche "web development" -> 0.5
    """
    niche_words = set(niche.lower().split())
    topic_words = set(re.findall(r"\w+", topic.lower()))
    if not niche_words:
        return 0.0
    return len(niche_words & topic_words) / len(niche_words)


def clean_and_rank(ideas: list[TopicIdea], niche: str) -> list[TopicIdea]:
    """Remove duplicates and junk, score relevance, and sort best first.

    Junk = website names (spam in "rising" trends) and the bare niche itself
    (too broad for one blog post). Ties keep their original order, so rising
    trends stay ahead of plain suggestions.
    """
    seen = set()
    ranked = []
    for idea in ideas:
        key = idea.topic.lower().strip()
        if (key in seen or key == niche.lower().strip() or LOOKS_LIKE_WEBSITE.search(key)
                or len(key.split()) < 2 or len(key.split()) > 10):
            continue
        seen.add(key)
        idea.relevance = round(relevance_score(idea.topic, niche), 2)
        ranked.append(idea)
    # sorted() is "stable": equal scores keep their earlier order.
    return sorted(ranked, key=lambda idea: idea.relevance, reverse=True)


def find_topics(niche: str, limit: int = 5) -> list[TopicIdea]:
    """Return the top `limit` topic ideas for a niche (Trends first, autocomplete as fallback)."""
    logger.info("Looking for trending topics in '%s'...", niche)
    ideas: list[TopicIdea] = []
    try:
        ideas = fetch_google_trends(niche)
        logger.info("Google Trends returned %d related searches.", len(ideas))
    except Exception as error:   # pytrends can fail in many ways (blocked, changed API, ...)
        logger.warning("Google Trends unavailable (%s). Using autocomplete instead.",
                       type(error).__name__)

    # Autocomplete adds variety, and is the only source if Trends failed.
    ideas += fetch_autocomplete_topics(niche)
    ranked = clean_and_rank(ideas, niche)
    if not ranked:
        raise ResearchError(f"Could not find any topics for '{niche}'. Check your internet "
                           "connection, or use manual mode.")
    return ranked[:limit]
