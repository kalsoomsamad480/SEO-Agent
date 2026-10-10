"""Page speed: LCP and FCP from the free Google PageSpeed Insights API.

LCP (Largest Contentful Paint): when the biggest thing on screen (hero image,
    headline) has loaded. Google's "is the page ready?" signal.
FCP (First Contentful Paint): when ANYTHING first appears. The "is it alive?" signal.

Google's official thresholds (lab values, in seconds):
            good      needs improvement     poor
    LCP     <= 2.5    <= 4.0                > 4.0
    FCP     <= 1.8    <= 3.0                > 3.0

One test takes 10-40 seconds because Google really loads the page.
Without PAGESPEED_API_KEY the shared free quota is often used up, so get a free key:
https://developers.google.com/speed/docs/insights/v5/get-started
"""

import requests

import config
from src.models.schemas import AuditIssue
from src.utils.logger import get_logger

logger = get_logger(__name__)

API_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
TIMEOUT_SECONDS = 120
# metric -> (good up to, needs improvement up to), in milliseconds
THRESHOLDS_MS = {"lcp": (2500, 4000), "fcp": (1800, 3000)}
AUDIT_NAMES = {"lcp": "largest-contentful-paint", "fcp": "first-contentful-paint"}
FIX_TIPS = {
    "lcp": "Compress and resize the main image (use WebP/AVIF), preload it, avoid lazy-loading "
           "it, and reduce slow server response time (caching, a CDN).",
    "fcp": "Remove or defer render-blocking CSS/JavaScript, inline critical CSS, "
           "and enable caching and compression on the server.",
}


class PageSpeedError(Exception):
    """PageSpeed Insights couldn't test the page (quota, timeout, bad URL...)."""


def rate(metric: str, milliseconds: float) -> str:
    """Label a value as "good", "needs improvement" or "poor" using Google's thresholds."""
    good, okay = THRESHOLDS_MS[metric]
    if milliseconds <= good:
        return "good"
    if milliseconds <= okay:
        return "needs improvement"
    return "poor"


def parse_response(data: dict) -> dict:
    """Pull LCP, FCP and the performance score out of the API's (very large) JSON reply."""
    lighthouse = data["lighthouseResult"]
    result: dict = {"performance_score": round((lighthouse["categories"]["performance"]["score"] or 0) * 100)}
    for metric, audit_name in AUDIT_NAMES.items():
        ms = lighthouse["audits"][audit_name]["numericValue"]
        result[metric] = {"seconds": round(ms / 1000, 2), "rating": rate(metric, ms)}
    return result


def run_pagespeed(url: str, strategy: str) -> dict:
    """Test one URL on "mobile" or "desktop". Raises PageSpeedError with a clear message."""
    params = {"url": url, "strategy": strategy, "category": "performance"}
    if config.PAGESPEED_API_KEY:
        params["key"] = config.PAGESPEED_API_KEY
    logger.info("Testing page speed (%s), this takes up to a minute...", strategy)
    try:
        response = requests.get(API_URL, params=params, timeout=TIMEOUT_SECONDS)
    except requests.RequestException as error:
        raise PageSpeedError(f"Could not reach PageSpeed Insights ({type(error).__name__}).") from None
    if response.status_code == 429:
        hint = "" if config.PAGESPEED_API_KEY else " Add a free PAGESPEED_API_KEY to .env."
        raise PageSpeedError("PageSpeed Insights quota is used up." + hint)
    if response.status_code != 200:
        raise PageSpeedError(f"PageSpeed Insights error {response.status_code}: {response.text[:200]}")
    try:
        return parse_response(response.json())
    except (KeyError, TypeError, ValueError):
        raise PageSpeedError("PageSpeed Insights returned an unexpected reply.") from None


def check_page_speed(url: str) -> tuple[dict, list[AuditIssue]]:
    """Test mobile and desktop. Returns (results for the report, issues for slow metrics).

    Errors are recorded in the results instead of stopping the whole audit.
    """
    results: dict = {"url": url}
    issues: list[AuditIssue] = []
    for strategy in ("mobile", "desktop"):
        try:
            scores = run_pagespeed(url, strategy)
        except PageSpeedError as error:
            logger.warning("Page speed (%s) skipped: %s", strategy, error)
            results[strategy] = {"error": str(error)}
            continue
        results[strategy] = scores
        for metric in ("lcp", "fcp"):
            rating = scores[metric]["rating"]
            if rating != "good":
                issues.append(AuditIssue(
                    page_url=url, issue_type=f"slow_{metric}",
                    severity="high" if rating == "poor" else "medium",
                    detail=f"{metric.upper()} on {strategy} is {scores[metric]['seconds']} s ({rating}).",
                    suggested_fix=FIX_TIPS[metric],
                ))
    return results, issues
