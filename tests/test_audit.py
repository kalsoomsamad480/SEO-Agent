"""Tests for the crawler, page speed parsing and the audit report (all offline)."""

from urllib.robotparser import RobotFileParser

import pytest

from src.audit import crawler, pagespeed, report
from src.models.schemas import AuditIssue, AuditReport

SITE = {
    "https://a.com/": '<a href="/about">About</a> <a href="/secret/x">S</a> '
                      '<a href="https://other.com/">Other</a> <a href="/logo.png">img</a> '
                      '<a href="mailto:me@a.com">mail</a> <a href="#top">top</a>',
    "https://a.com/about": '<a href="/">Home</a> <a href="/about#team">Team</a> <a href="/blog">Blog</a>',
    "https://a.com/blog": "<p>blog</p>",
}


def fake_fetch(url):
    if url in SITE:
        return crawler.PageData(url=url, status=200, html=SITE[url], final_url=url)
    return crawler.PageData(url=url, status=404, final_url=url)


def robots_from(text: str) -> RobotFileParser:
    parser = RobotFileParser()
    parser.parse(text.splitlines())
    return parser


# --- crawler ----------------------------------------------------------------------
def test_normalize_url():
    assert crawler.normalize_url("HTTPS://A.com/about#team") == "https://a.com/about"
    assert crawler.normalize_url("https://a.com") == "https://a.com/"


def test_extract_links_makes_absolute_and_skips_mailto_and_anchors():
    links = crawler.extract_links(SITE["https://a.com/"], "https://a.com/")
    assert links == ["https://a.com/about", "https://a.com/secret/x", "https://other.com/",
                     "https://a.com/logo.png"]


def test_crawl_stays_on_site_obeys_robots_and_skips_files():
    robots = robots_from("User-agent: *\nDisallow: /secret/")
    result = crawler.crawl("https://a.com", max_pages=10, delay=0, fetch=fake_fetch, robots=robots)
    crawled = [p.url for p in result.pages]
    assert crawled == ["https://a.com/", "https://a.com/about", "https://a.com/blog"]
    assert result.blocked_by_robots == ["https://a.com/secret/x"]
    assert "https://other.com/" not in crawled    # other domain
    assert "https://a.com/logo.png" not in crawled  # an image, not a page


def test_crawl_respects_max_pages():
    result = crawler.crawl("https://a.com", max_pages=2, delay=0, fetch=fake_fetch,
                           robots=robots_from(""))
    assert len(result.pages) == 2


def test_crawl_does_not_follow_links_after_redirect_to_other_site():
    def redirecting_fetch(url):
        return crawler.PageData(url=url, status=200, html='<a href="/x">x</a>',
                                final_url="https://elsewhere.com/")
    result = crawler.crawl("https://a.com", max_pages=10, delay=0, fetch=redirecting_fetch,
                           robots=robots_from(""))
    assert len(result.pages) == 1


# --- page speed --------------------------------------------------------------------
def test_rate_uses_google_thresholds():
    assert pagespeed.rate("lcp", 2400) == "good"
    assert pagespeed.rate("lcp", 3000) == "needs improvement"
    assert pagespeed.rate("lcp", 4500) == "poor"
    assert pagespeed.rate("fcp", 1800) == "good"
    assert pagespeed.rate("fcp", 3100) == "poor"


def test_parse_response():
    sample = {"lighthouseResult": {
        "categories": {"performance": {"score": 0.72}},
        "audits": {"largest-contentful-paint": {"numericValue": 3200.4},
                   "first-contentful-paint": {"numericValue": 1100}}}}
    assert pagespeed.parse_response(sample) == {
        "performance_score": 72,
        "lcp": {"seconds": 3.2, "rating": "needs improvement"},
        "fcp": {"seconds": 1.1, "rating": "good"},
    }


def test_check_page_speed_records_errors_instead_of_crashing(monkeypatch):
    def quota_used_up(url, strategy):
        raise pagespeed.PageSpeedError("quota is used up")
    monkeypatch.setattr(pagespeed, "run_pagespeed", quota_used_up)
    results, issues = pagespeed.check_page_speed("https://a.com/")
    assert results["mobile"] == {"error": "quota is used up"}
    assert issues == []


def test_check_page_speed_creates_issues_for_slow_metrics(monkeypatch):
    slow = {"performance_score": 30, "lcp": {"seconds": 5.0, "rating": "poor"},
            "fcp": {"seconds": 1.0, "rating": "good"}}
    monkeypatch.setattr(pagespeed, "run_pagespeed", lambda url, strategy: slow)
    _results, issues = pagespeed.check_page_speed("https://a.com/")
    assert [(i.issue_type, i.severity) for i in issues] == [("slow_lcp", "high"), ("slow_lcp", "high")]


# --- report ------------------------------------------------------------------------
def make_issue(severity, kind="missing_h1", url="https://a.com/"):
    return AuditIssue(page_url=url, issue_type=kind, severity=severity, detail="d", suggested_fix="fix it")


def test_sort_issues_puts_high_first():
    issues = report.sort_issues([make_issue("low"), make_issue("high"), make_issue("medium")])
    assert [i.severity for i in issues] == ["high", "medium", "low"]


def test_markdown_report_groups_by_severity_with_fixes():
    audit = AuditReport(site_url="https://a.com/", pages_crawled=3,
                        issues=[make_issue("high", "page_404"), make_issue("low", "empty_alt")],
                        page_speed={"url": "https://a.com/", "mobile": {"error": "quota"}})
    text = report.to_markdown(audit)
    assert text.index("## High priority (1)") < text.index("## Low priority (1)")
    assert "### Page 404" in text and "**How to fix:** fix it" in text
    assert "| mobile | - | - | - | quota |" in text


def test_run_audit_with_fake_crawl(monkeypatch):
    fake_result = crawler.CrawlResult(start_url="https://a.com/")
    fake_result.pages = [crawler.PageData("https://a.com/", 200, "<title>T</title><h1>H</h1>"),
                         crawler.PageData("https://a.com/gone", 404)]
    fake_result.links = {"https://a.com/": ["https://a.com/gone"]}
    monkeypatch.setattr(crawler, "crawl", lambda url, max_pages: fake_result)
    audit = report.run_audit("a.com", check_speed=False)
    kinds = {i.issue_type for i in audit.issues}
    assert {"page_404", "broken_internal_link", "missing_meta_description"} <= kinds
    assert audit.issues[0].severity == "high"


def test_run_audit_with_nothing_crawled_gives_friendly_error(monkeypatch):
    monkeypatch.setattr(crawler, "crawl", lambda url, max_pages: crawler.CrawlResult(start_url=url))
    with pytest.raises(ValueError, match="No pages could be crawled"):
        report.run_audit("https://a.com", check_speed=False)
