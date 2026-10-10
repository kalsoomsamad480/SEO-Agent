"""Run the full audit and turn the results into readable reports.

    crawl the site -> run every check -> (optional) page speed
                   -> (optional) LLM explanation -> save audit.json + audit.md

Detection is 100% plain code. The LLM (if --explain is used) only writes a
friendly summary of what the code already found.
"""

import json
import time
from datetime import datetime
from pathlib import Path

import config
from src.audit import checks, crawler, pagespeed
from src.models.schemas import AuditIssue, AuditReport
from src.utils.logger import get_logger

logger = get_logger(__name__)

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
MAX_EXAMPLES_PER_TYPE = 3


def polite_link_checker(site_domain: str):
    """A link checker that pauses before each request to the audited site.

    Links to OTHER sites are spread over many servers, so they don't need the pause.
    """
    def check(url: str) -> int | None:
        if crawler.domain_of(url) == site_domain:
            time.sleep(config.CRAWL_DELAY_SECONDS)
        return crawler.check_link_status(url)
    return check


def sort_issues(issues: list[AuditIssue]) -> list[AuditIssue]:
    """Most severe first; then grouped by issue type and page."""
    return sorted(issues, key=lambda i: (SEVERITY_ORDER[i.severity], i.issue_type, i.page_url))


def run_audit(site_url: str, max_pages: int = config.DEFAULT_MAX_PAGES,
              check_external: bool = True, check_speed: bool = True,
              explain: bool = False) -> AuditReport:
    """Crawl a site, run every check, and return the AuditReport."""
    if not site_url.startswith(("http://", "https://")):
        site_url = "https://" + site_url
    logger.info("Auditing %s (up to %d pages)...", site_url, max_pages)

    result = crawler.crawl(site_url, max_pages=max_pages)
    if not result.pages:
        raise ValueError(f"No pages could be crawled at {site_url}. robots.txt may block "
                         "crawling, or the address is wrong.")

    html_pages = {p.url: p.html for p in result.pages if p.html and p.status == 200}
    statuses = {p.url: p.status for p in result.pages}
    issues: list[AuditIssue] = []

    logger.info("Checking content, titles and images on %d page(s)...", len(html_pages))
    issues += checks.find_error_pages(statuses)
    issues += checks.find_duplicate_content(html_pages)
    issues += checks.find_duplicate_titles(html_pages)
    issues += checks.find_duplicate_meta_descriptions(html_pages)
    for url, html in html_pages.items():
        issues += checks.check_basic_tags(url, html)
        issues += checks.find_missing_alt(url, html)

    logger.info("Checking links (this can take a while)...")
    site_domain = crawler.domain_of(result.start_url)
    link_issues, links_checked = checks.find_broken_links(
        result.links, site_domain, statuses,
        link_checker=polite_link_checker(site_domain), check_external=check_external)
    issues += link_issues

    speed: dict = {}
    if check_speed:
        speed, speed_issues = pagespeed.check_page_speed(result.start_url)
        issues += speed_issues

    report = AuditReport(
        site_url=result.start_url,
        pages_crawled=len(result.pages),
        pages_blocked_by_robots=len(result.blocked_by_robots),
        links_checked=links_checked,
        issues=sort_issues(issues),
        page_speed=speed,
    )
    if explain:
        report.explanation = explain_with_llm(report)
    logger.info("Audit done: %d high, %d medium, %d low priority issue(s).",
                report.count("high"), report.count("medium"), report.count("low"))
    return report


# ---------------------------------------------------------------------------
# Optional LLM explanation
# ---------------------------------------------------------------------------
def summarize_issues(issues: list[AuditIssue]) -> str:
    """One line per issue type: count and an example (keeps the LLM prompt small)."""
    by_type: dict[str, list[AuditIssue]] = {}
    for issue in issues:
        by_type.setdefault(issue.issue_type, []).append(issue)
    lines = [f"- {kind} ({items[0].severity}): {len(items)}, e.g. {items[0].detail}"
             for kind, items in by_type.items()]
    return "\n".join(lines) or "- (no issues found)"


def explain_with_llm(report: AuditReport) -> str:
    """Ask the LLM for a plain-language summary. Never stops the audit if the LLM fails."""
    from src.llm.client import LLMError, get_client, load_prompt

    prompt = load_prompt("audit_explain", site_url=report.site_url,
                         pages_crawled=report.pages_crawled,
                         issue_summary=summarize_issues(report.issues),
                         page_speed=json.dumps(report.page_speed) if report.page_speed else "(not tested)")
    try:
        logger.info("Asking the AI to explain the results...")
        return get_client().generate_text(prompt, system=load_prompt("system"))
    except (LLMError, config.ConfigError) as error:
        logger.warning("AI explanation skipped: %s", error)
        return ""


# ---------------------------------------------------------------------------
# Readable report
# ---------------------------------------------------------------------------
def _speed_rows(page_speed: dict) -> list[str]:
    rows = []
    for strategy in ("mobile", "desktop"):
        data = page_speed.get(strategy)
        if not data:
            continue
        if "error" in data:
            rows.append(f"| {strategy} | - | - | - | {data['error']} |")
        else:
            rows.append(f"| {strategy} | {data['performance_score']}/100 "
                        f"| {data['lcp']['seconds']} s ({data['lcp']['rating']}) "
                        f"| {data['fcp']['seconds']} s ({data['fcp']['rating']}) | |")
    return rows


def to_markdown(report: AuditReport) -> str:
    """Build the human-readable audit report."""
    lines = [
        f"# SEO Audit: {report.site_url}",
        "",
        f"Date: {report.created_at:%Y-%m-%d %H:%M}  ",
        f"Pages crawled: {report.pages_crawled}  ",
        f"Pages blocked by robots.txt (not crawled): {report.pages_blocked_by_robots}  ",
        f"Links checked: {report.links_checked}",
        "",
        "| Priority | Issues |",
        "|---|---|",
        f"| High | {report.count('high')} |",
        f"| Medium | {report.count('medium')} |",
        f"| Low | {report.count('low')} |",
        "",
    ]
    if report.explanation:
        lines += ["## Summary (AI explanation, based only on the findings below)", "",
                  report.explanation.strip(), ""]

    speed_rows = _speed_rows(report.page_speed)
    if speed_rows:
        lines += [f"## Page speed ({report.page_speed.get('url', report.site_url)})", "",
                  "| Device | Score | LCP | FCP | Note |", "|---|---|---|---|---|", *speed_rows,
                  "", "Good: LCP up to 2.5 s, FCP up to 1.8 s.", ""]

    for severity in ("high", "medium", "low"):
        group = [i for i in report.issues if i.severity == severity]
        if not group:
            continue
        lines += [f"## {severity.capitalize()} priority ({len(group)})", ""]
        current_type = None
        for issue in group:
            if issue.issue_type != current_type:
                current_type = issue.issue_type
                lines += ["", f"### {current_type.replace('_', ' ').capitalize()}", "",
                          f"**How to fix:** {issue.suggested_fix}", ""]
            lines.append(f"- {issue.page_url}: {issue.detail}")
        lines.append("")

    if not report.issues:
        lines += ["No issues found. Nice work!", ""]
    return "\n".join(lines)


def save_report(report: AuditReport) -> Path:
    """Save audit.json and audit.md in outputs/audits/<domain>-<date-time>/."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    folder = config.AUDITS_DIR / f"{crawler.domain_of(report.site_url)}-{stamp}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "audit.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
    (folder / "audit.md").write_text(to_markdown(report), encoding="utf-8")
    logger.info("Audit report saved to %s", folder)
    return folder
