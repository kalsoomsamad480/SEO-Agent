"""Crawl a website politely and collect each page's HTML and links.

Polite means:
    - we obey robots.txt (the site's rules for bots), including its Crawl-delay
    - we only visit pages on the same domain
    - we stop after max_pages (default 50)
    - we wait between requests, so we never hammer the server
    - we identify ourselves with a clear User-Agent

The crawler only COLLECTS data. Finding problems happens in checks.py.
"""

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import urldefrag, urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

import config
from src.utils.logger import get_logger

logger = get_logger(__name__)

SKIPPED_SCHEMES = ("mailto:", "tel:", "javascript:", "data:", "#")
# File types that are never HTML pages, so we don't download them while crawling.
NON_PAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".pdf", ".zip",
                       ".mp4", ".mp3", ".css", ".js", ".ico", ".xml", ".woff", ".woff2")


@dataclass
class PageData:
    """What we got back for one URL."""
    url: str
    status: int | None             # HTTP status, None if the request failed
    html: str = ""                 # empty for non-HTML responses
    error: str = ""                # e.g. "Timeout" when status is None
    final_url: str = ""            # where we ended up after redirects


@dataclass
class CrawlResult:
    """Everything the crawler collected."""
    start_url: str
    pages: list[PageData] = field(default_factory=list)
    links: dict[str, list[str]] = field(default_factory=dict)   # page URL -> links found on it
    blocked_by_robots: list[str] = field(default_factory=list)


RETRY_WAIT_SECONDS = 3

# One shared Session re-uses the same connection for many requests (keep-alive):
# faster for us, and gentler on the server than opening a new connection every time.
_session = requests.Session()
_session.headers["User-Agent"] = config.USER_AGENT

# A fetcher downloads one URL. Tests pass a fake one with sample HTML.
Fetcher = Callable[[str], PageData]


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------
def normalize_url(url: str) -> str:
    """Make equivalent URLs identical: drop #fragments, lowercase the domain, add "/" to bare domains."""
    url, _fragment = urldefrag(url.strip())
    parts = urlparse(url)
    path = parts.path or "/"
    normalized = f"{parts.scheme.lower()}://{parts.netloc.lower()}{path}"
    return normalized + (f"?{parts.query}" if parts.query else "")


def domain_of(url: str) -> str:
    """Domain without "www.", so www.example.com and example.com count as the same site."""
    return urlparse(url).netloc.lower().removeprefix("www.")


def is_same_site(url: str, start_url: str) -> bool:
    return domain_of(url) == domain_of(start_url)


def looks_like_page(url: str) -> bool:
    """False for images, PDFs and other files we shouldn't crawl as pages."""
    return not urlparse(url).path.lower().endswith(NON_PAGE_EXTENSIONS)


def extract_links(html: str, page_url: str) -> list[str]:
    """Return every http(s) link on a page as an absolute, normalized URL (no duplicates)."""
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        if not href or href.lower().startswith(SKIPPED_SCHEMES):
            continue
        absolute = normalize_url(urljoin(page_url, href))   # turns "/about" into a full URL
        if absolute.startswith(("http://", "https://")) and absolute not in links:
            links.append(absolute)
    return links


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------
def fetch_page(url: str) -> PageData:
    """Download one URL. Only HTML is kept; network errors become status=None."""
    try:
        response = _session.get(url, timeout=config.HTTP_TIMEOUT_SECONDS, allow_redirects=True)
    except requests.RequestException as error:
        return PageData(url=url, status=None, error=type(error).__name__)
    is_html = "text/html" in response.headers.get("Content-Type", "")
    return PageData(url=url, status=response.status_code, html=response.text if is_html else "",
                    final_url=response.url)


def check_link_status(url: str) -> int | None:
    """Return a link's HTTP status, or None if it can't be reached even after one retry.

    HEAD asks for headers only (no page body), so it's light. Some servers don't
    support HEAD, so on an error status we confirm with a normal GET.
    A dropped connection is often temporary, so we wait and retry once before
    calling the link broken.
    """
    for attempt in (1, 2):
        try:
            response = _session.head(url, timeout=config.HTTP_TIMEOUT_SECONDS, allow_redirects=True)
            if response.status_code >= 400:
                response = _session.get(url, timeout=config.HTTP_TIMEOUT_SECONDS,
                                        allow_redirects=True, stream=True)
                response.close()
            return response.status_code
        except requests.RequestException as error:
            if attempt == 2:
                logger.warning("No response from %s (%s)", url, type(error).__name__)
                return None
            time.sleep(RETRY_WAIT_SECONDS)
    return None


def load_robots(start_url: str) -> RobotFileParser:
    """Download and parse robots.txt.

    No robots.txt (404) = everything allowed. 401/403 = treat the whole site as off-limits,
    the same rule Python's standard library uses.
    """
    robots_url = urljoin(start_url, "/robots.txt")
    parser = RobotFileParser(robots_url)
    try:
        response = requests.get(robots_url, headers={"User-Agent": config.USER_AGENT},
                                timeout=config.HTTP_TIMEOUT_SECONDS)
        if response.status_code in (401, 403):
            parser.disallow_all = True
        elif response.status_code == 200:
            parser.parse(response.text.splitlines())
        else:
            parser.allow_all = True
    except requests.RequestException:
        logger.warning("Could not read robots.txt; crawling carefully anyway.")
        parser.allow_all = True
    return parser


# ---------------------------------------------------------------------------
# The crawl
# ---------------------------------------------------------------------------
def crawl(start_url: str, max_pages: int = config.DEFAULT_MAX_PAGES,
          delay: float = config.CRAWL_DELAY_SECONDS, fetch: Fetcher = fetch_page,
          robots: RobotFileParser | None = None) -> CrawlResult:
    """Visit up to max_pages pages of one site, breadth-first, starting at start_url.

    Breadth-first means we visit pages close to the home page first, which are
    usually the most important ones.
    """
    start_url = normalize_url(start_url)
    robots = robots or load_robots(start_url)
    # If robots.txt asks for a longer pause than ours, respect it.
    delay = max(delay, float(robots.crawl_delay(config.USER_AGENT) or 0))

    result = CrawlResult(start_url=start_url)
    queue = deque([start_url])
    seen = {start_url}

    while queue and len(result.pages) < max_pages:
        url = queue.popleft()
        if not robots.can_fetch(config.USER_AGENT, url):
            result.blocked_by_robots.append(url)
            continue

        if result.pages:
            time.sleep(delay)   # no wait before the first page
        page = fetch(url)
        result.pages.append(page)
        logger.info("Crawled %d/%d: %s (%s)", len(result.pages), max_pages, url,
                    page.status or page.error)

        if not page.html:
            continue
        if page.final_url and not is_same_site(page.final_url, start_url):
            continue   # redirected to another website: don't follow its links
        links = extract_links(page.html, url)
        result.links[url] = links
        for link in links:
            if link not in seen and is_same_site(link, start_url) and looks_like_page(link):
                seen.add(link)
                queue.append(link)

    logger.info("Crawl finished: %d page(s), %d blocked by robots.txt.",
                len(result.pages), len(result.blocked_by_robots))
    return result
