"""Technical SEO checks: plain code that finds problems in crawled pages.

Every function takes plain data (URLs and HTML strings) and returns a list
of AuditIssue objects, so each check can be tested with tiny HTML samples
and no internet.

Severity guide:
    high   = hurts users or rankings right now (404s, broken links, duplicate pages)
    medium = clear SEO problem worth fixing soon (missing title/description/H1/alt)
    low    = small improvement or worth a quick look
"""

import hashlib
import re
from itertools import combinations
from typing import Callable

from bs4 import BeautifulSoup

from src.models.schemas import AuditIssue
from src.utils.logger import get_logger

logger = get_logger(__name__)

NEAR_DUPLICATE_THRESHOLD = 0.9   # 90% of 3-word phrases shared = near-duplicate
MIN_WORDS_FOR_DUPLICATE_CHECK = 50   # tiny pages (login, contact) are too short to judge

# Default fix for each issue type. The LLM may add a friendlier explanation later.
FIX_HINTS = {
    "page_404": "Restore the page, or 301-redirect its URL to the closest relevant page, "
                "and update every link pointing to it.",
    "page_error": "Check the server logs for this URL and fix the error, or redirect it.",
    "broken_internal_link": "Update the link to a working page, or remove it.",
    "broken_external_link": "Replace the link with a working source, or remove it.",
    "unverified_link": "Open the link in your browser. If it works, ignore this: the site blocks bots.",
    "duplicate_content": "Merge the pages, or add a canonical tag on the copy pointing to the main version.",
    "near_duplicate_content": "Rewrite one page so it covers a distinct topic, or merge them "
                              "and redirect the weaker one.",
    "duplicate_title": "Give every page its own title (under 60 characters) describing its content.",
    "duplicate_meta_description": "Write a unique meta description (under 160 characters) for each page.",
    "missing_title": "Add a <title> tag with the page's main keyword.",
    "missing_meta_description": "Add a meta description summarising the page in under 160 characters.",
    "missing_h1": "Add one <h1> heading that says what the page is about.",
    "multiple_h1": "Keep one <h1> per page; change the others to <h2>.",
    "missing_alt": "Add alt text that describes the image (include a keyword only if it fits naturally).",
    "empty_alt": "Fine for purely decorative images. Otherwise, describe the image in the alt text.",
}


def make_issue(page_url: str, issue_type: str, severity: str, detail: str) -> AuditIssue:
    """Build an AuditIssue with the default fix hint for its type."""
    return AuditIssue(page_url=page_url, issue_type=issue_type, severity=severity,
                      detail=detail, suggested_fix=FIX_HINTS.get(issue_type, ""))


# ---------------------------------------------------------------------------
# Reading HTML
# ---------------------------------------------------------------------------
def visible_text(html: str) -> str:
    """The words a visitor actually reads (scripts and styles removed), in lower case."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    return " ".join(soup.get_text(" ").split()).lower()


def get_title(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    return soup.title.get_text(strip=True) if soup.title else ""


def get_meta_description(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find("meta", attrs={"name": re.compile("^description$", re.IGNORECASE)})
    return (tag.get("content") or "").strip() if tag else ""


def text_fingerprint(text: str) -> str:
    """A short "fingerprint" (hash) of the text: identical text = identical fingerprint."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def shingles(text: str, size: int = 3) -> set[str]:
    """All overlapping 3-word phrases in the text ("the cat sat", "cat sat on", ...)."""
    words = text.split()
    return {" ".join(words[i:i + size]) for i in range(len(words) - size + 1)}


def similarity(text_a: str, text_b: str) -> float:
    """How similar two texts are, from 0.0 (nothing shared) to 1.0 (same phrases).

    Jaccard similarity: shared phrases / all phrases. Comparing 3-word phrases
    instead of single words means "same words, different meaning" doesn't count.
    """
    a, b = shingles(text_a), shingles(text_b)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# ---------------------------------------------------------------------------
# Duplicate content, titles, descriptions
# ---------------------------------------------------------------------------
def find_duplicate_content(pages: dict[str, str]) -> list[AuditIssue]:
    """Find pages with identical or near-identical text. pages = {url: html}."""
    texts = {url: visible_text(html) for url, html in pages.items()}
    texts = {url: t for url, t in texts.items() if len(t.split()) >= MIN_WORDS_FOR_DUPLICATE_CHECK}
    issues: list[AuditIssue] = []

    # 1) Exact duplicates: group pages by fingerprint.
    by_fingerprint: dict[str, list[str]] = {}
    for url, text in texts.items():
        by_fingerprint.setdefault(text_fingerprint(text), []).append(url)
    exact_pairs = set()
    for urls in by_fingerprint.values():
        for other in urls[1:]:
            issues.append(make_issue(other, "duplicate_content", "high",
                                     f"Same text as {urls[0]}"))
            exact_pairs.add(frozenset((urls[0], other)))

    # 2) Near duplicates: compare every pair once (fine for a 50-page crawl).
    for url_a, url_b in combinations(texts, 2):
        if frozenset((url_a, url_b)) in exact_pairs or texts[url_a] == texts[url_b]:
            continue
        score = similarity(texts[url_a], texts[url_b])
        if score >= NEAR_DUPLICATE_THRESHOLD:
            issues.append(make_issue(url_b, "near_duplicate_content", "medium",
                                     f"{score:.0%} similar to {url_a}"))
    return issues


def _find_repeated(values: dict[str, str], issue_type: str, label: str) -> list[AuditIssue]:
    """Flag pages that share the same (non-empty) value, e.g. the same title."""
    groups: dict[str, list[str]] = {}
    for url, value in values.items():
        if value:
            groups.setdefault(value.lower(), []).append(url)
    issues = []
    for urls in groups.values():
        if len(urls) > 1:
            for url in urls:
                others = len(urls) - 1
                issues.append(make_issue(url, issue_type, "medium",
                                         f"Same {label} as {others} other page(s): \"{values[url]}\""))
    return issues


def find_duplicate_titles(pages: dict[str, str]) -> list[AuditIssue]:
    return _find_repeated({u: get_title(h) for u, h in pages.items()}, "duplicate_title", "title")


def find_duplicate_meta_descriptions(pages: dict[str, str]) -> list[AuditIssue]:
    return _find_repeated({u: get_meta_description(h) for u, h in pages.items()},
                          "duplicate_meta_description", "meta description")


# ---------------------------------------------------------------------------
# Per-page checks
# ---------------------------------------------------------------------------
def check_basic_tags(url: str, html: str) -> list[AuditIssue]:
    """Missing title, missing meta description, missing H1, or more than one H1."""
    issues = []
    if not get_title(html):
        issues.append(make_issue(url, "missing_title", "medium", "No <title> tag."))
    if not get_meta_description(html):
        issues.append(make_issue(url, "missing_meta_description", "medium", "No meta description."))
    h1_count = len(BeautifulSoup(html, "html.parser").find_all("h1"))
    if h1_count == 0:
        issues.append(make_issue(url, "missing_h1", "medium", "No <h1> heading."))
    elif h1_count > 1:
        issues.append(make_issue(url, "multiple_h1", "low", f"{h1_count} <h1> headings."))
    return issues


def find_missing_alt(url: str, html: str) -> list[AuditIssue]:
    """Images without alt text. Missing attribute = medium; alt="" = low (OK if decorative)."""
    issues = []
    for img in BeautifulSoup(html, "html.parser").find_all("img"):
        src = img.get("src") or img.get("data-src") or "(no src)"
        if not img.has_attr("alt"):
            issues.append(make_issue(url, "missing_alt", "medium", f"Image without alt: {src}"))
        elif not img["alt"].strip():
            issues.append(make_issue(url, "empty_alt", "low", f"Image with empty alt: {src}"))
    return issues


# ---------------------------------------------------------------------------
# Status codes and links
# ---------------------------------------------------------------------------
def find_error_pages(statuses: dict[str, int | None]) -> list[AuditIssue]:
    """Crawled pages that returned 404, another 4xx/5xx, or no response."""
    issues = []
    for url, status in statuses.items():
        if status == 404:
            issues.append(make_issue(url, "page_404", "high", "Page returns 404 Not Found."))
        elif status is None or status >= 400:
            issues.append(make_issue(url, "page_error", "high",
                                     f"Page returns {status or 'no response (timeout or connection error)'}."))
    return issues


# Statuses that usually mean "this site blocks bots", not "this link is broken".
BOT_BLOCK_STATUSES = {401, 403, 429, 999}


def is_broken(status: int | None) -> bool:
    """A link is broken if it gives no response, or a 4xx/5xx status (except bot blocks)."""
    return status is None or (status >= 400 and status not in BOT_BLOCK_STATUSES)


def find_broken_links(links: dict[str, list[str]], site_domain: str,
                      known_statuses: dict[str, int | None],
                      link_checker: Callable[[str], int | None],
                      check_external: bool = True, max_checks: int = 300) -> tuple[list[AuditIssue], int]:
    """Check every link found on the crawled pages.

    links: page URL -> links on that page.
    known_statuses: statuses we already have from crawling (no need to request them again).
    Returns (issues, number of links checked).
    """
    from src.audit.crawler import domain_of   # small helper shared with the crawler

    status_cache = dict(known_statuses)
    checked = 0
    issues: list[AuditIssue] = []
    for page_url, page_links in links.items():
        for link in page_links:
            internal = domain_of(link) == site_domain
            if not internal and not check_external:
                continue
            if link not in status_cache:
                if checked >= max_checks:
                    continue   # safety limit so huge sites don't take forever
                status_cache[link] = link_checker(link)
                checked += 1
            status = status_cache[link]
            if status in BOT_BLOCK_STATUSES:
                issues.append(make_issue(page_url, "unverified_link", "low",
                                         f"Link to {link} returned {status} (the site may block bots)."))
            elif is_broken(status):
                kind = "broken_internal_link" if internal else "broken_external_link"
                issues.append(make_issue(page_url, kind, "high",
                                         f"Link to {link} returns {status or 'no response'}."))
    return issues, checked
