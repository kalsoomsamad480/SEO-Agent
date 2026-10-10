"""Find backlink opportunities for a blog. LIST ONLY: nothing is ever submitted.

Two sources:
1. Well-known platforms for each category (always available, no key needed).
2. Search results from the official Brave Search API (only if BRAVE_SEARCH_API_KEY is set).
   We never scrape Google or other search engines' result pages: their terms forbid bots.
   Without a key you get the search queries to run yourself instead.

Quality rules (low-quality links can get a site penalized, so we filter hard):
    - skip anything that sells links or "guest post services" (paid links break Google's rules)
    - skip big social/marketplace sites in search results (not real opportunities)
    - score relevance to your niche and keyword, and sort the best first
"""

import re
import time

import requests

import config
from src.models.schemas import Opportunity
from src.offpage.tracker import make_id, today
from src.utils import text_tools as tt
from src.utils.logger import get_logger

logger = get_logger(__name__)

CATEGORIES = {
    "web2_profile": "Web 2.0 and profile backlinks",
    "contextual": "Contextual backlinks (links inside relevant content)",
    "article_submission": "Blog post / article submission",
    "image_submission": "Image submission",
    "audio_submission": "Audio submission",
    "guest_post": "Guest posting",
}

# Well-known, legitimate platforms. "topics" = niches where the platform fits best;
# an empty list means it fits any niche.
PLATFORMS = [
    ("web2_profile", "Medium (profile + posts)", "https://medium.com", []),
    ("web2_profile", "WordPress.com blog", "https://wordpress.com", []),
    ("web2_profile", "Blogger", "https://www.blogger.com", []),
    ("web2_profile", "Tumblr", "https://www.tumblr.com", []),
    ("web2_profile", "GitHub profile", "https://github.com", ["web", "developer", "programming", "code", "software", "python", "tech"]),
    ("web2_profile", "About.me profile", "https://about.me", []),
    ("article_submission", "LinkedIn articles", "https://www.linkedin.com", ["business", "marketing", "career", "b2b", "tech"]),
    ("article_submission", "DEV Community", "https://dev.to", ["web", "developer", "programming", "code", "software", "python", "tech"]),
    ("article_submission", "Hashnode", "https://hashnode.com", ["web", "developer", "programming", "code", "software", "tech"]),
    ("article_submission", "Substack", "https://substack.com", []),
    ("image_submission", "Pinterest", "https://www.pinterest.com", ["food", "recipe", "design", "fashion", "home", "travel", "diy", "craft"]),
    ("image_submission", "Flickr", "https://www.flickr.com", ["photo", "travel", "nature", "art"]),
    ("image_submission", "Behance", "https://www.behance.net", ["design", "art", "ui", "web", "brand"]),
    ("audio_submission", "SoundCloud", "https://soundcloud.com", ["music", "audio", "podcast"]),
    ("audio_submission", "Spotify for Creators (podcast)", "https://creators.spotify.com", []),
]

# Search "footprints": phrases that real guest-post and resource pages contain.
SEARCH_FOOTPRINTS = {
    "guest_post": ['{kw} "write for us"', '{kw} "guest post guidelines"', '{kw} "contribute an article"'],
    "contextual": ['{kw} "useful resources"', '{kw} "recommended reading"'],
}

PAID_LINK_WORDS = re.compile(r"buy (backlinks|links|guest post)|guest post service|sponsored post price|"
                             r"link insertion|cheap backlinks|\bpbn\b|link farm", re.IGNORECASE)
SKIP_DOMAINS = ("facebook.com", "instagram.com", "youtube.com", "twitter.com", "x.com", "reddit.com",
                "quora.com", "amazon.com", "fiverr.com", "upwork.com", "pinterest.com", "tiktok.com")
BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
SEARCH_PAUSE_SECONDS = 1.1    # the free plan allows about 1 query per second


def meaningful_words(text: str) -> set[str]:
    """Lower-case words longer than 3 letters (skips "the", "for", "and"...)."""
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 3}


def relevance(text: str, keywords: list[str]) -> float:
    """Share of the keywords' meaningful words that appear in the text (0.0-1.0)."""
    wanted = set().union(*(meaningful_words(k) for k in keywords)) if keywords else set()
    if not wanted:
        return 0.0
    return round(len(wanted & meaningful_words(text)) / len(wanted), 2)


def platform_opportunities(niche: str, blog_slug: str) -> list[Opportunity]:
    """Built-in platforms, scored by how well they fit the niche."""
    niche_words = meaningful_words(niche) | set(niche.lower().split())
    found = []
    for category, name, url, topics in PLATFORMS:
        if not topics:
            score = 0.5                       # fits any niche
        elif niche_words & set(topics):
            score = 0.8                       # made for this kind of niche
        else:
            continue                          # wrong audience (e.g. SoundCloud for a law firm)
        found.append(Opportunity(id=make_id(url, blog_slug), opportunity=name, category=category,
                                 url=url, relevance=score, date=today(), blog_slug=blog_slug,
                                 notes="Platform: create the profile/post yourself."))
    return found


def build_search_queries(keyword: str, niche: str) -> dict[str, list[str]]:
    """Footprint queries per category, e.g. 'web development "write for us"'."""
    queries = {}
    for category, patterns in SEARCH_FOOTPRINTS.items():
        queries[category] = [p.format(kw=term) for term in dict.fromkeys([niche, keyword]) if term
                             for p in patterns]
    return queries


def brave_search(query: str, count: int = 10) -> list[dict]:
    """Search with the Brave Search API. Returns [{"title", "url", "description"}] or []."""
    try:
        response = requests.get(BRAVE_URL, params={"q": query, "count": count},
                                headers={"X-Subscription-Token": config.BRAVE_SEARCH_API_KEY,
                                         "Accept": "application/json"},
                                timeout=config.HTTP_TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.json().get("web", {}).get("results", [])
    except (requests.RequestException, ValueError) as error:
        logger.warning("Search failed for %s (%s)", query, type(error).__name__)
        return []


def is_acceptable_result(result: dict) -> bool:
    """Reject paid-link sellers and big social/marketplace sites."""
    domain = tt.get_domain(result.get("url", ""))
    text = f"{result.get('title', '')} {result.get('description', '')}"
    if not domain or any(domain == d or domain.endswith("." + d) for d in SKIP_DOMAINS):
        return False
    return not PAID_LINK_WORDS.search(text)


def search_opportunities(queries: dict[str, list[str]], keywords: list[str], blog_slug: str,
                         search=brave_search) -> list[Opportunity]:
    """Run the footprint queries and turn good results into opportunities."""
    found: dict[str, Opportunity] = {}
    for category, category_queries in queries.items():
        for query in category_queries:
            for result in search(query):
                if not is_acceptable_result(result):
                    continue
                text = f"{result.get('title', '')} {result.get('description', '')}"
                score = relevance(text, keywords)
                if score == 0:
                    continue   # nothing to do with our topic
                item = Opportunity(id=make_id(result["url"], blog_slug),
                                   opportunity=result.get("title", "")[:80] or tt.get_domain(result["url"]),
                                   category=category, url=result["url"], relevance=score,
                                   date=today(), blog_slug=blog_slug,
                                   notes=re.sub(r"<[^>]+>", "", result.get("description", ""))[:200])
                if item.id not in found or found[item.id].relevance < score:
                    found[item.id] = item
            time.sleep(SEARCH_PAUSE_SECONDS)
    return list(found.values())


def find_opportunities(niche: str, focus_keyword: str, blog_slug: str,
                       search=None) -> tuple[list[Opportunity], dict[str, list[str]]]:
    """Return (opportunities sorted best first, the search queries used or to run yourself)."""
    keywords = [k for k in (niche, focus_keyword) if k]
    queries = build_search_queries(focus_keyword, niche)
    items = platform_opportunities(niche or focus_keyword, blog_slug)

    if search is None and config.BRAVE_SEARCH_API_KEY:
        search = brave_search
    if search:
        logger.info("Searching for guest-post and resource pages...")
        items += search_opportunities(queries, keywords, blog_slug, search=search)
    else:
        logger.info("No BRAVE_SEARCH_API_KEY: showing platforms plus search queries to run yourself.")
    items.sort(key=lambda item: item.relevance, reverse=True)
    return items, queries
