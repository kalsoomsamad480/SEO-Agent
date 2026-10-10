"""On-page SEO validator: plain-code checks, no AI.

Why no AI? These rules have exact answers ("is the keyword in the title?"),
so code is faster, free, and always gives the same result for the same input.

Each rule is a small function that takes a BlogDraft and returns a RuleResult
(pass/fail + reason + fix hint). `validate_blog` runs all of them.

Thresholds come from config.py. Each rule also accepts them as arguments,
so tests can use tiny examples (e.g. min_words=20 instead of 1000).
"""

import re
from typing import Callable

import requests

import config
from src.models.schemas import BlogDraft, RuleResult, ValidationReport
from src.utils import text_tools as tt
from src.utils.logger import get_logger

logger = get_logger(__name__)

# A link checker takes a URL and returns its HTTP status code (or None if unreachable).
# Tests pass a fake one so they never touch the internet.
LinkChecker = Callable[[str], int | None]

FAQ_HEADING_PATTERN = re.compile(r"\bfaqs?\b|frequently asked questions", re.IGNORECASE)
# Numbers that look like statistics: "45%", "3.5 percent", "2 million", "1 in 4"
STATISTIC_PATTERN = re.compile(
    r"\d+(?:\.\d+)?\s?(?:%|percent\b|million\b|billion\b)|\b\d+ (?:in|out of) \d+\b",
    re.IGNORECASE,
)


class BlogInputError(ValueError):
    """Raised when a pasted blog is missing something we need (like the focus keyword)."""


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _pass(rule_id: str, name: str, reason: str) -> RuleResult:
    return RuleResult(rule_id=rule_id, name=name, passed=True, reason=reason)


def _fail(rule_id: str, name: str, reason: str, fix_hint: str) -> RuleResult:
    return RuleResult(rule_id=rule_id, name=name, passed=False, reason=reason, fix_hint=fix_hint)


def _skip(rule_id: str, name: str, reason: str) -> RuleResult:
    return RuleResult(rule_id=rule_id, name=name, passed=True, skipped=True, reason=reason)


def _body_text(draft: BlogDraft) -> str:
    """The article as plain text (what readers see), used for counting words."""
    return tt.markdown_to_plain_text(draft.body_markdown)


def _h1_texts(draft: BlogDraft) -> list[str]:
    return [h.text for h in tt.extract_headings(draft.body_markdown) if h.level == 1]


def is_authority_domain(domain: str) -> bool:
    """True if the domain is a government/university site or on our trusted list."""
    if domain.endswith(config.AUTHORITY_SUFFIXES):
        return True
    # "en.wikipedia.org" counts because it ends with ".wikipedia.org".
    return any(domain == d or domain.endswith("." + d) for d in config.AUTHORITY_DOMAINS)


def get_external_links(draft: BlogDraft) -> list[tt.Link]:
    """Links that point to OTHER websites (not your site, main page or child pages)."""
    own_domain = tt.get_domain(draft.site_url) if draft.site_url else ""
    own_urls = {draft.main_page_url, *draft.child_page_urls}
    external = []
    for link in tt.extract_links(draft.body_markdown):
        if not link.url.startswith(("http://", "https://")):
            continue   # relative links like "/about" are internal
        if link.url in own_urls or (own_domain and tt.get_domain(link.url) == own_domain):
            continue
        external.append(link)
    return external


def default_link_checker(url: str) -> int | None:
    """Return the HTTP status code of a URL, or None if it can't be reached.

    We try a light HEAD request first. Some servers refuse HEAD, so we fall
    back to a normal GET (with stream=True, so we don't download the whole page).
    """
    headers = {"User-Agent": config.USER_AGENT}
    try:
        response = requests.head(url, headers=headers, allow_redirects=True,
                                 timeout=config.HTTP_TIMEOUT_SECONDS)
        if response.status_code >= 400:
            response = requests.get(url, headers=headers, allow_redirects=True,
                                    timeout=config.HTTP_TIMEOUT_SECONDS, stream=True)
            response.close()
        return response.status_code
    except requests.RequestException as error:
        logger.warning("Could not reach %s (%s)", url, type(error).__name__)
        return None


# ---------------------------------------------------------------------------
# Focus keyword placement
# ---------------------------------------------------------------------------
def check_keyword_in_title(draft: BlogDraft) -> RuleResult:
    """The focus keyword must be in the title tag AND the H1."""
    rule, name = "keyword_in_title", "Focus keyword in title and H1"
    kw = draft.focus_keyword
    missing = []
    if not tt.contains_keyword(draft.title, kw):
        missing.append("title tag")
    if not any(tt.contains_keyword(h1, kw) for h1 in _h1_texts(draft)):
        missing.append("H1")
    if missing:
        return _fail(rule, name, f"'{kw}' not found in: {', '.join(missing)}.",
                     f"Rewrite the {' and '.join(missing)} to include '{kw}', ideally near the start.")
    return _pass(rule, name, "Keyword found in title tag and H1.")


def check_keyword_in_first_words(draft: BlogDraft, window: int = config.FIRST_WORDS_WINDOW) -> RuleResult:
    """The focus keyword must appear in the first N words of the article (after the H1)."""
    rule, name = "keyword_in_intro", f"Focus keyword in first {window} words"
    # Drop the H1 line so the title itself doesn't count as the intro.
    body_without_h1 = re.sub(r"^\s*#\s+.*$", "", draft.body_markdown, count=1, flags=re.MULTILINE)
    intro = tt.first_n_words(tt.markdown_to_plain_text(body_without_h1), window)
    if tt.contains_keyword(intro, draft.focus_keyword):
        return _pass(rule, name, f"Keyword appears in the first {window} words.")
    return _fail(rule, name, f"Keyword not in the first {window} words.",
                 f"Use '{draft.focus_keyword}' in the first or second sentence of the intro.")


def check_keyword_in_h2(draft: BlogDraft) -> RuleResult:
    """At least one H2 heading must contain the focus keyword."""
    rule, name = "keyword_in_h2", "Focus keyword in at least one H2"
    h2s = [h.text for h in tt.extract_headings(draft.body_markdown) if h.level == 2]
    if any(tt.contains_keyword(h2, draft.focus_keyword) for h2 in h2s):
        return _pass(rule, name, "Keyword found in an H2.")
    return _fail(rule, name, f"None of the {len(h2s)} H2 headings contain the keyword.",
                 f"Rename one H2 to include '{draft.focus_keyword}'.")


def check_keyword_in_meta_description(draft: BlogDraft) -> RuleResult:
    """The meta description must contain the focus keyword."""
    rule, name = "keyword_in_meta_description", "Focus keyword in meta description"
    if tt.contains_keyword(draft.meta_description, draft.focus_keyword):
        return _pass(rule, name, "Keyword found in meta description.")
    return _fail(rule, name, "Keyword missing from meta description.",
                 f"Rewrite the meta description to include '{draft.focus_keyword}'.")


def check_keyword_in_slug(draft: BlogDraft) -> RuleResult:
    """The URL slug must contain the focus keyword (as hyphenated words)."""
    rule, name = "keyword_in_slug", "Focus keyword in URL slug"
    keyword_slug = tt.slugify(draft.focus_keyword)
    slug = tt.slugify(draft.slug)
    if keyword_slug and keyword_slug in slug:
        return _pass(rule, name, f"Slug '{slug}' contains '{keyword_slug}'.")
    return _fail(rule, name, f"Slug '{draft.slug or '(empty)'}' doesn't contain '{keyword_slug}'.",
                 f"Use a short slug such as '{keyword_slug}'.")


def check_image_alt(draft: BlogDraft) -> RuleResult:
    """The feature image needs alt text that contains the focus keyword."""
    rule, name = "image_alt_keyword", "Feature image alt text has focus keyword"
    if not draft.feature_image_alt.strip():
        return _fail(rule, name, "No feature image alt text.",
                     f"Add a feature image with alt text describing it and including '{draft.focus_keyword}'.")
    if tt.contains_keyword(draft.feature_image_alt, draft.focus_keyword):
        return _pass(rule, name, "Alt text contains the keyword.")
    return _fail(rule, name, f"Alt text '{draft.feature_image_alt}' lacks the keyword.",
                 f"Describe the image naturally and include '{draft.focus_keyword}'.")


# ---------------------------------------------------------------------------
# Length and keyword usage
# ---------------------------------------------------------------------------
def check_min_words(draft: BlogDraft, min_words: int = config.MIN_WORDS) -> RuleResult:
    """The article must be at least MIN_WORDS long."""
    rule, name = "min_word_count", f"At least {min_words} words"
    count = tt.word_count(_body_text(draft))
    if count >= min_words:
        return _pass(rule, name, f"{count} words.")
    return _fail(rule, name, f"Only {count} words ({min_words - count} short).",
                 "Expand sections with useful detail, examples or steps. Don't add filler.")


def check_keyword_count(draft: BlogDraft, minimum: int = config.MIN_FOCUS_KEYWORD_COUNT) -> RuleResult:
    """The focus keyword must be used at least `minimum` times in the article."""
    rule, name = "keyword_min_count", f"Focus keyword used at least {minimum} times"
    count = tt.keyword_count(_body_text(draft), draft.focus_keyword)
    if count >= minimum:
        return _pass(rule, name, f"Used {count} times.")
    return _fail(rule, name, f"Used only {count} times.",
                 f"Add '{draft.focus_keyword}' {minimum - count} more time(s) where it reads naturally.")


def check_keyword_density(draft: BlogDraft, max_percent: float = config.MAX_KEYWORD_DENSITY_PERCENT) -> RuleResult:
    """The keyword must not be overused (keyword stuffing hurts rankings)."""
    rule, name = "keyword_density", f"Keyword density at most {max_percent}%"
    density = tt.keyword_density(_body_text(draft), draft.focus_keyword)
    if density <= max_percent:
        return _pass(rule, name, f"Density {density:.2f}%.")
    return _fail(rule, name, f"Density {density:.2f}% is too high (keyword stuffing).",
                 "Replace some uses of the keyword with synonyms or pronouns.")


def check_secondary_keywords(draft: BlogDraft) -> RuleResult:
    """Each secondary keyword should appear at least once."""
    rule, name = "secondary_keywords", "Secondary keywords used"
    if not draft.secondary_keywords:
        return _skip(rule, name, "No secondary keywords given.")
    text = _body_text(draft)
    missing = [kw for kw in draft.secondary_keywords if not tt.contains_keyword(text, kw)]
    if not missing:
        return _pass(rule, name, f"All {len(draft.secondary_keywords)} secondary keywords used.")
    return _fail(rule, name, f"Missing: {', '.join(missing)}.",
                 "Work each missing phrase into a relevant paragraph or H3.")


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------
def check_single_h1(draft: BlogDraft) -> RuleResult:
    """There must be exactly one H1 (the article's main heading)."""
    rule, name = "single_h1", "Exactly one H1"
    count = len(_h1_texts(draft))
    if count == 1:
        return _pass(rule, name, "One H1 found.")
    return _fail(rule, name, f"Found {count} H1 headings.",
                 "Keep one '# H1' at the top. Change the others to '## H2'." if count > 1
                 else "Add one '# H1' heading at the top of the article.")


def check_heading_structure(draft: BlogDraft, min_h2: int = config.MIN_H2_HEADINGS) -> RuleResult:
    """Headings must be logical: start with H1, no skipped levels, enough H2 sections."""
    rule, name = "heading_structure", "Logical H2/H3 structure"
    headings = tt.extract_headings(draft.body_markdown)
    problems = []
    if headings and headings[0].level != 1:
        problems.append("the first heading is not the H1")
    for previous, current in zip(headings, headings[1:]):
        # Going deeper by more than one level (H2 -> H4) skips a level.
        if current.level - previous.level > 1:
            problems.append(f"'{current.text}' jumps from H{previous.level} to H{current.level}")
    h2_count = sum(1 for h in headings if h.level == 2)
    if h2_count < min_h2:
        problems.append(f"only {h2_count} H2 heading(s), need {min_h2}")
    if not problems:
        return _pass(rule, name, f"{len(headings)} headings in a logical order.")
    message = "; ".join(problems)
    # Upper-case only the first letter (.capitalize() would lower-case "H2" to "h2").
    return _fail(rule, name, message[0].upper() + message[1:] + ".",
                 "Use H1 -> H2 -> H3 in order. Each main section is an H2, sub-points are H3.")


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------
def check_authority_link(draft: BlogDraft, minimum: int = config.MIN_EXTERNAL_LINKS) -> RuleResult:
    """At least `minimum` links must go to high-authority sites (.gov, .edu, trusted list)."""
    rule, name = "authority_link", f"At least {minimum} high-authority external link(s)"
    external = get_external_links(draft)
    authority = [link for link in external if is_authority_domain(tt.get_domain(link.url))]
    if len(authority) >= minimum:
        domains = sorted({tt.get_domain(link.url) for link in authority})
        return _pass(rule, name, f"Authority links to: {', '.join(domains)}.")
    reason = f"{len(authority)} authority link(s) out of {len(external)} external link(s)."
    return _fail(rule, name, reason,
                 "Link a relevant fact to a trusted source: a .gov or .edu site, official documentation, "
                 "Wikipedia or a major publisher. Add trusted domains in config.AUTHORITY_DOMAINS.")


def check_external_links_live(draft: BlogDraft, link_checker: LinkChecker | None = None) -> RuleResult:
    """Every external link must respond with HTTP 200 (no dead or made-up links).

    Needs the internet, so it only runs when a link_checker is given.
    """
    rule, name = "external_links_live", "External links respond with 200"
    if link_checker is None:
        return _skip(rule, name, "Not checked (run with link checking on).")
    urls = sorted({link.url for link in get_external_links(draft)})
    if not urls:
        return _skip(rule, name, "No external links to check.")
    bad = []
    for url in urls:
        status = link_checker(url)
        if status != 200:
            bad.append(f"{url} ({status or 'unreachable'})")
    if not bad:
        return _pass(rule, name, f"All {len(urls)} external link(s) returned 200.")
    return _fail(rule, name, f"Bad links: {'; '.join(bad)}.",
                 "Replace each bad link with a working page from a trusted source, or remove it.")


def check_internal_links(draft: BlogDraft) -> RuleResult:
    """Child pages link to their main page; a main page links to every child page."""
    rule, name = "internal_links", "Main page <-> child page links"
    if not draft.main_page_url and not draft.child_page_urls:
        return _skip(rule, name, "Not part of a main/child page group.")
    linked = {link.url.rstrip("/") for link in tt.extract_links(draft.body_markdown)}
    required = [u for u in [draft.main_page_url, *draft.child_page_urls] if u]
    missing = [u for u in required if u.rstrip("/") not in linked]
    if not missing:
        return _pass(rule, name, f"All {len(required)} required internal link(s) present.")
    return _fail(rule, name, f"Missing links to: {', '.join(missing)}.",
                 "Add a link to each page with descriptive anchor text (the page's topic, not 'click here').")


def check_descriptive_anchors(draft: BlogDraft) -> RuleResult:
    """Links must use descriptive anchor text, not "click here"."""
    rule, name = "descriptive_anchors", "Descriptive link anchor text"
    generic = [link.anchor for link in tt.extract_links(draft.body_markdown)
               if link.anchor.lower().strip(" .!") in config.GENERIC_ANCHOR_TEXTS]
    if not generic:
        return _pass(rule, name, "No generic anchors found.")
    return _fail(rule, name, f"Generic anchor text: {', '.join(repr(a) for a in generic)}.",
                 "Use words that describe the target page, e.g. 'beginner's guide to coffee grinders'.")


# ---------------------------------------------------------------------------
# FAQ
# ---------------------------------------------------------------------------
def get_faq_questions(draft: BlogDraft) -> list[tt.Section] | None:
    """Return the FAQ questions (H3s ending in '?') or None if there is no FAQ H2."""
    sections = tt.split_sections(draft.body_markdown)
    faq_index = next((i for i, s in enumerate(sections)
                      if s.level == 2 and FAQ_HEADING_PATTERN.search(s.title)), None)
    if faq_index is None:
        return None
    questions = []
    for section in sections[faq_index + 1:]:
        if section.level <= 2:
            break   # the FAQ ends where the next H2 starts
        if section.level == 3 and section.title.rstrip().endswith("?"):
            questions.append(section)
    return questions


def check_faq_section(draft: BlogDraft, minimum: int = config.MIN_FAQ_QUESTIONS) -> RuleResult:
    """There must be an FAQ H2 as the LAST section, with at least `minimum` questions."""
    rule, name = "faq_section", f"FAQ section at the end with {minimum}+ questions"
    questions = get_faq_questions(draft)
    if questions is None:
        return _fail(rule, name, "No FAQ section found.",
                     "Add '## Frequently Asked Questions' at the end, with each question as a '### ...?' H3.")
    h2s = [h for h in tt.extract_headings(draft.body_markdown) if h.level == 2]
    if not FAQ_HEADING_PATTERN.search(h2s[-1].text):
        return _fail(rule, name, f"FAQ is not the last section ('{h2s[-1].text}' comes after it).",
                     "Move the FAQ section to the end of the article.")
    if len(questions) < minimum:
        return _fail(rule, name, f"Only {len(questions)} question(s).",
                     f"Add {minimum - len(questions)} more real question(s) as H3 headings ending in '?'.")
    return _pass(rule, name, f"{len(questions)} FAQ questions at the end.")


def check_faq_answers_short(draft: BlogDraft, max_words: int = config.FAQ_MAX_ANSWER_WORDS) -> RuleResult:
    """FAQ answers must be short and direct (good for AI answer engines)."""
    rule, name = "faq_answers_short", f"FAQ answers short (1-{max_words} words)"
    questions = get_faq_questions(draft)
    if not questions:
        return _skip(rule, name, "No FAQ questions to check.")
    problems = []
    for q in questions:
        words = tt.word_count(tt.markdown_to_plain_text(q.content))
        if words == 0 or words > max_words:
            problems.append(f"'{q.title}' has {words} words")
    if not problems:
        return _pass(rule, name, f"All {len(questions)} answers are short and direct.")
    return _fail(rule, name, "; ".join(problems) + ".",
                 "Answer in 1-3 sentences. Start with the direct answer (e.g. 'Yes, ...').")


# ---------------------------------------------------------------------------
# Quality guardrails
# ---------------------------------------------------------------------------
def check_statistics_sourced(draft: BlogDraft) -> RuleResult:
    """Any paragraph with a statistic (45%, 2 million, 1 in 4) must contain a source link."""
    rule, name = "statistics_sourced", "Statistics have a linked source"
    unsourced = []
    for paragraph in re.split(r"\n\s*\n", draft.body_markdown):
        if paragraph.lstrip().startswith("#"):
            continue
        if STATISTIC_PATTERN.search(paragraph) and not tt.extract_links(paragraph):
            snippet = tt.markdown_to_plain_text(paragraph).strip()[:60]
            unsourced.append(f"'{snippet}...'")
    if not unsourced:
        return _pass(rule, name, "No unsourced statistics.")
    return _fail(rule, name, f"Statistic without a source link: {'; '.join(unsourced)}.",
                 "Link each statistic to the real source it came from, or remove the number. Never invent figures.")


def get_min_reading_ease(audience: str) -> int:
    """Look up the minimum reading-ease score for an audience from config."""
    audience = audience.lower()
    for key, score in config.AUDIENCE_MIN_READING_EASE.items():
        if key in audience:
            return score
    return config.DEFAULT_MIN_READING_EASE


def check_audience_reading_level(draft: BlogDraft) -> RuleResult:
    """The text must be easy enough to read for the target audience."""
    rule, name = "audience_reading_level", "Reading level fits the audience"
    if not draft.audience.strip():
        return _skip(rule, name, "No target audience given.")
    minimum = get_min_reading_ease(draft.audience)
    score = tt.flesch_reading_ease(_body_text(draft))
    if score >= minimum:
        return _pass(rule, name, f"Reading ease {score} (needs {minimum}+ for '{draft.audience}').")
    return _fail(rule, name, f"Reading ease {score} is below {minimum} for '{draft.audience}'.",
                 "Use shorter sentences, simpler words, and explain any jargon the first time you use it.")


def check_meta_lengths(draft: BlogDraft) -> list[RuleResult]:
    """Title tag and meta description must exist and fit Google's display limits."""
    results = []
    for rule, label, value, limit in [
        ("title_length", "Title tag", draft.title, config.TITLE_MAX_CHARS),
        ("meta_description_length", "Meta description", draft.meta_description,
         config.META_DESCRIPTION_MAX_CHARS),
    ]:
        name = f"{label} 1-{limit} characters"
        length = len(value.strip())
        if 0 < length <= limit:
            results.append(_pass(rule, name, f"{length} characters."))
        else:
            hint = (f"Write a {label.lower()}." if length == 0
                    else f"Shorten it by {length - limit} characters. Keep the keyword near the start.")
            results.append(_fail(rule, name, f"{length} characters.", hint))
    return results


# ---------------------------------------------------------------------------
# Run everything
# ---------------------------------------------------------------------------
def validate_blog(draft: BlogDraft, check_links: bool = False,
                  link_checker: LinkChecker | None = None) -> ValidationReport:
    """Run every SEO rule on a draft and return the full report.

    check_links=True checks external links over the internet (slower).
    link_checker lets tests swap in a fake checker.
    """
    if check_links and link_checker is None:
        link_checker = default_link_checker

    results = [
        check_keyword_in_title(draft),
        check_keyword_in_first_words(draft),
        check_keyword_in_h2(draft),
        check_keyword_in_meta_description(draft),
        check_keyword_in_slug(draft),
        check_image_alt(draft),
        *check_meta_lengths(draft),
        check_min_words(draft),
        check_keyword_count(draft),
        check_keyword_density(draft),
        check_secondary_keywords(draft),
        check_single_h1(draft),
        check_heading_structure(draft),
        check_authority_link(draft),
        check_external_links_live(draft, link_checker),
        check_faq_section(draft),
        check_faq_answers_short(draft),
        check_internal_links(draft),
        check_descriptive_anchors(draft),
        check_statistics_sourced(draft),
        check_audience_reading_level(draft),
    ]
    report = ValidationReport(focus_keyword=draft.focus_keyword, results=results)
    logger.info("Validated '%s': %s", draft.focus_keyword, report.score)
    return report


def load_draft_from_markdown(text: str, **overrides: str) -> BlogDraft:
    """Build a BlogDraft from pasted Markdown, with an optional settings block on top.

    Missing values are filled sensibly: title from the H1, image alt from the
    first image. `overrides` (e.g. focus_keyword="...") win over the file.
    """
    settings, body = tt.split_front_matter(text)
    settings.update({key: value for key, value in overrides.items() if value})

    focus_keyword = settings.get("focus_keyword", "").strip()
    if not focus_keyword:
        raise BlogInputError("No focus keyword. Add 'focus_keyword: ...' at the top of the file "
                             "or pass --keyword.")

    h1s = [h.text for h in tt.extract_headings(body) if h.level == 1]
    images = tt.extract_images(body)

    def as_list(value: str) -> list[str]:
        return [item.strip() for item in value.split(",") if item.strip()]

    return BlogDraft(
        title=settings.get("title") or (h1s[0] if h1s else ""),
        meta_description=settings.get("meta_description", ""),
        slug=settings.get("slug", ""),
        focus_keyword=focus_keyword,
        secondary_keywords=as_list(settings.get("secondary_keywords", "")),
        body_markdown=body,
        feature_image_alt=settings.get("feature_image_alt") or (images[0].alt if images else ""),
        feature_image_url=settings.get("feature_image_url") or (images[0].url if images else ""),
        audience=settings.get("audience", ""),
        site_url=settings.get("site_url", ""),
        main_page_url=settings.get("main_page_url") or None,
        child_page_urls=as_list(settings.get("child_page_urls", "")),
    )


def format_report(report: ValidationReport) -> str:
    """Turn a report into a readable plain-text table for the console.

    Uses PASS/FAIL/SKIP words instead of emoji so it prints on every Windows console.
    """
    lines = [f"SEO report for '{report.focus_keyword}': {report.score}", "-" * 70]
    for r in report.results:
        status = "SKIP" if r.skipped else ("PASS" if r.passed else "FAIL")
        lines.append(f"[{status}] {r.name}: {r.reason}")
        if not r.passed and not r.skipped:
            lines.append(f"        Fix: {r.fix_hint}")
    lines.append("-" * 70)
    lines.append("RESULT: PASSED" if report.passed else f"RESULT: {len(report.failed_rules)} rule(s) failed")
    return "\n".join(lines)
