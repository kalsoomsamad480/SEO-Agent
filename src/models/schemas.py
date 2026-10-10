"""Data models shared across the project, built with Pydantic.

A model is like a form with labelled boxes. Pydantic checks that each box
holds the right kind of value (text, number, list) and gives a clear error
if not, so bad data is caught early instead of causing odd bugs later.

Flow of data through the agent:
    BlogRequest -> KeywordPlan -> BlogDraft -> ValidationReport
    (a website URL) -> AuditReport
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class BlogRequest(BaseModel):
    """What you want written. Comes from the 3 manual questions or auto mode."""
    topic: str
    audience: str = "beginners"
    tone: str = "friendly and clear"
    goal: Literal["educate", "rank", "sales", "leads"] = "educate"
    niche: str = ""
    main_page_url: str | None = None   # set this when the blog is a child page
    main_page_title: str = ""          # used as the link's anchor text


class TopicIdea(BaseModel):
    """A topic found in auto mode, with where it came from and how relevant it is."""
    topic: str
    source: str                        # "google trends (top)", "google autocomplete", ...
    relevance: float = 0.0             # 0.0-1.0, how well it matches your niche


class ResearchChoice(BaseModel):
    """The LLM's keyword decision (checked and cleaned in code afterwards)."""
    focus_keyword: str
    secondary_keywords: list[str] = Field(default_factory=list)
    source_suggestions: list[str] = Field(default_factory=list)   # URLs to verify, never trusted blindly


class FaqChoice(BaseModel):
    """The questions the LLM picked from the real-question list."""
    questions: list[str]


class KeywordPlan(BaseModel):
    """The research result: which keywords to target and what to include."""
    topic: str
    focus_keyword: str
    secondary_keywords: list[str] = Field(default_factory=list)
    faq_questions: list[str] = Field(default_factory=list)
    authority_links: list[str] = Field(default_factory=list)   # verified URLs (HTTP 200)


class OutlineSection(BaseModel):
    """One H2 section of the outline, with optional H3 sub-points."""
    h2: str
    h3s: list[str] = Field(default_factory=list)
    notes: str = ""                    # what to cover, which keywords to use here


class BlogOutline(BaseModel):
    """The plan for the article, created by the LLM before writing."""
    h1: str
    intro_notes: str
    sections: list[OutlineSection]
    faq_questions: list[str]


class BlogMetadata(BaseModel):
    """SEO metadata that all reuse the same focus keyword."""
    title: str                         # <title> tag, max TITLE_MAX_CHARS
    meta_description: str              # max META_DESCRIPTION_MAX_CHARS
    slug: str
    feature_image_alt: str


class BlogDraft(BaseModel):
    """One blog post plus its SEO metadata. This is what the validator checks."""
    title: str                         # the <title> tag shown in Google results
    meta_description: str
    slug: str                          # the URL part, e.g. "how-to-brew-coffee"
    focus_keyword: str
    secondary_keywords: list[str] = Field(default_factory=list)
    body_markdown: str                 # the full article, starting with one "# H1"
    feature_image_alt: str = ""
    feature_image_url: str = ""
    audience: str = ""
    site_url: str = ""                 # your own site, so its links count as internal
    main_page_url: str | None = None   # child page: must link here
    child_page_urls: list[str] = Field(default_factory=list)  # main page: must link to all


class RuleResult(BaseModel):
    """The outcome of one SEO rule."""
    rule_id: str                       # short code, e.g. "min_word_count"
    name: str                          # human-readable, e.g. "At least 1000 words"
    passed: bool
    reason: str                        # what we found
    fix_hint: str = ""                 # how to fix it (empty when passed)
    skipped: bool = False              # True when the rule doesn't apply / wasn't run


class ValidationReport(BaseModel):
    """All rule results for one blog draft."""
    focus_keyword: str
    results: list[RuleResult]
    created_at: datetime = Field(default_factory=datetime.now)

    @property
    def failed_rules(self) -> list[RuleResult]:
        """Rules that ran and failed (skipped rules are not failures)."""
        return [r for r in self.results if not r.passed and not r.skipped]

    @property
    def passed(self) -> bool:
        """True when no rule failed."""
        return not self.failed_rules

    @property
    def score(self) -> str:
        """Short summary like "17/19 rules passed"."""
        ran = [r for r in self.results if not r.skipped]
        passed = sum(1 for r in ran if r.passed)
        return f"{passed}/{len(ran)} rules passed"


class Opportunity(BaseModel):
    """One backlink opportunity = one row in the CSV tracker.

    Status flow (a human moves it forward; the code never sends anything):
        found -> draft -> approved -> sent      (or -> rejected at any point)
    """
    id: str                            # short code made from url + blog, used in commands
    opportunity: str                   # site/platform name or page title
    category: str                      # one of offpage.opportunities.CATEGORIES
    url: str
    relevance: float = 0.0             # 0.0-1.0
    status: Literal["found", "draft", "approved", "sent", "rejected"] = "found"
    date: str = ""                     # date of the last change, YYYY-MM-DD
    blog_slug: str = ""                # which blog this is for
    draft_file: str = ""               # path of the drafted pitch/description
    notes: str = ""


class AuditIssue(BaseModel):
    """One technical SEO problem found on a website (used from Phase 6)."""
    page_url: str
    issue_type: str                    # e.g. "missing_alt", "broken_link", "duplicate_title"
    severity: Literal["high", "medium", "low"]
    detail: str
    suggested_fix: str = ""


class AuditReport(BaseModel):
    """The full technical audit of a website (used from Phase 6)."""
    site_url: str
    pages_crawled: int = 0
    pages_blocked_by_robots: int = 0
    links_checked: int = 0
    issues: list[AuditIssue] = Field(default_factory=list)
    page_speed: dict = Field(default_factory=dict)   # filled by pagespeed.py
    explanation: str = ""              # optional plain-language summary written by the LLM
    created_at: datetime = Field(default_factory=datetime.now)

    def count(self, severity: str) -> int:
        """How many issues have this severity ("high", "medium" or "low")."""
        return sum(1 for issue in self.issues if issue.severity == severity)
