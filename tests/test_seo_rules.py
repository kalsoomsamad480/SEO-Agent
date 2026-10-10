"""Tests for src/validators/seo_rules.py.

Each rule gets at least one example that passes and one that fails.
`make_draft()` builds a small, valid draft; each test changes only the part
it is testing, so it's easy to see why that rule passes or fails.
"""

from src.models.schemas import BlogDraft
from src.validators import seo_rules as rules

KEYWORD = "coffee grinder"

GOOD_BODY = """# How to Choose a Coffee Grinder

A coffee grinder helps you make fresher coffee at home. It is easy to learn.

![A burr coffee grinder on a table](https://example.com/grinder.jpg)

## Why a Coffee Grinder Matters

Fresh grounds taste better. The [FDA food safety guide](https://www.fda.gov/food) has tips on storing food.

### Burr or Blade

Burr models crush beans evenly.

## Frequently Asked Questions

### Is a coffee grinder worth it?

Yes. Fresh coffee tastes better.

### How often should I clean it?

Clean it once a week.

### Can I grind spices in it?

Use a separate grinder for spices.
"""


def make_draft(**changes) -> BlogDraft:
    """A small draft that passes the rules; pass keyword arguments to break one part."""
    values = dict(
        title="Coffee Grinder Guide for Beginners",
        meta_description="Learn how to choose a coffee grinder with this simple guide.",
        slug="coffee-grinder-guide",
        focus_keyword=KEYWORD,
        secondary_keywords=["burr"],
        body_markdown=GOOD_BODY,
        feature_image_alt="A burr coffee grinder on a table",
        audience="beginners",
    )
    values.update(changes)
    return BlogDraft(**values)


def long_good_body() -> str:
    """A full-length (1000+ words) article that should pass every rule."""
    filler = "You can start small and learn as you go. Taste each cup and write down what you like. " * 20
    return f"""# How to Choose a Coffee Grinder

A coffee grinder helps you make fresher coffee at home. {filler}

![A burr coffee grinder on a table](https://example.com/grinder.jpg)

## Why a Coffee Grinder Matters

{filler} The [FDA food safety guide](https://www.fda.gov/food) explains how to store food well.

### Burr or Blade

{filler} A burr coffee grinder gives an even grind.

## How to Use Your New Grinder

{filler} Clean your coffee grinder often.

## Frequently Asked Questions

### Is a coffee grinder worth it?

Yes. Fresh coffee tastes better.

### How often should I clean it?

Clean it once a week.

### Can I grind spices in it?

Use a separate grinder for spices.
"""


# --- keyword placement --------------------------------------------------------
def test_keyword_in_title_passes():
    assert rules.check_keyword_in_title(make_draft()).passed


def test_keyword_in_title_fails_when_missing_from_title_tag():
    result = rules.check_keyword_in_title(make_draft(title="A Guide for Beginners"))
    assert not result.passed
    assert "title tag" in result.reason


def test_keyword_in_title_fails_when_missing_from_h1():
    body = GOOD_BODY.replace("# How to Choose a Coffee Grinder", "# Better Coffee at Home")
    result = rules.check_keyword_in_title(make_draft(body_markdown=body))
    assert not result.passed
    assert "H1" in result.reason


def test_keyword_in_first_words_passes():
    assert rules.check_keyword_in_first_words(make_draft()).passed


def test_keyword_in_first_words_fails_when_keyword_comes_late():
    body = "# Coffee Grinder\n\n" + "word " * 120 + "coffee grinder"
    assert not rules.check_keyword_in_first_words(make_draft(body_markdown=body)).passed


def test_keyword_in_h2_passes_and_fails():
    assert rules.check_keyword_in_h2(make_draft()).passed
    body = GOOD_BODY.replace("## Why a Coffee Grinder Matters", "## Why It Matters")
    assert not rules.check_keyword_in_h2(make_draft(body_markdown=body)).passed


def test_keyword_in_meta_description_passes_and_fails():
    assert rules.check_keyword_in_meta_description(make_draft()).passed
    assert not rules.check_keyword_in_meta_description(make_draft(meta_description="A guide.")).passed


def test_keyword_in_slug_passes_and_fails():
    assert rules.check_keyword_in_slug(make_draft()).passed
    assert not rules.check_keyword_in_slug(make_draft(slug="grinder-guide")).passed


def test_image_alt_passes_and_fails():
    assert rules.check_image_alt(make_draft()).passed
    assert not rules.check_image_alt(make_draft(feature_image_alt="")).passed
    assert not rules.check_image_alt(make_draft(feature_image_alt="A photo of a kitchen")).passed


# --- meta lengths -------------------------------------------------------------
def test_meta_lengths_pass():
    assert all(r.passed for r in rules.check_meta_lengths(make_draft()))


def test_meta_lengths_fail_when_too_long_or_empty():
    title_result, meta_result = rules.check_meta_lengths(
        make_draft(title="x" * 61, meta_description="")
    )
    assert not title_result.passed
    assert not meta_result.passed


# --- length and keyword usage ----------------------------------------------
def test_min_words_passes_and_fails():
    assert rules.check_min_words(make_draft(), min_words=20).passed
    assert not rules.check_min_words(make_draft(), min_words=1000).passed


def test_keyword_count_passes_and_fails():
    # GOOD_BODY uses "coffee grinder" 4 times (H1, intro, H2, FAQ question).
    assert rules.check_keyword_count(make_draft(), minimum=4).passed
    assert not rules.check_keyword_count(make_draft(), minimum=5).passed


def test_keyword_density_fails_when_stuffed():
    stuffed = "# Coffee Grinder\n\n" + "coffee grinder is great. " * 10
    assert not rules.check_keyword_density(make_draft(body_markdown=stuffed), max_percent=2.0).passed


def test_keyword_density_passes_for_normal_text():
    assert rules.check_keyword_density(make_draft(body_markdown=long_good_body())).passed


def test_secondary_keywords():
    assert rules.check_secondary_keywords(make_draft()).passed
    assert not rules.check_secondary_keywords(make_draft(secondary_keywords=["espresso"])).passed
    assert rules.check_secondary_keywords(make_draft(secondary_keywords=[])).skipped


# --- structure ----------------------------------------------------------------
def test_single_h1_passes_and_fails():
    assert rules.check_single_h1(make_draft()).passed
    assert not rules.check_single_h1(make_draft(body_markdown=GOOD_BODY + "\n# Second H1\n")).passed
    assert not rules.check_single_h1(make_draft(body_markdown="## Only H2\n\ntext")).passed


def test_heading_structure_passes():
    assert rules.check_heading_structure(make_draft()).passed


def test_heading_structure_fails_on_skipped_level():
    body = GOOD_BODY.replace("### Burr or Blade", "#### Burr or Blade")
    result = rules.check_heading_structure(make_draft(body_markdown=body))
    assert not result.passed
    assert "H2 to H4" in result.reason


def test_heading_structure_fails_with_too_few_h2():
    body = "# Coffee Grinder\n\n## Only One Section\n\ntext"
    assert not rules.check_heading_structure(make_draft(body_markdown=body)).passed


# --- links --------------------------------------------------------------------
def test_authority_link_passes_for_gov_site():
    assert rules.check_authority_link(make_draft()).passed


def test_authority_link_fails_for_unknown_site():
    body = GOOD_BODY.replace("https://www.fda.gov/food", "https://random-blog.example/food")
    assert not rules.check_authority_link(make_draft(body_markdown=body)).passed


def test_links_to_own_site_are_not_external():
    body = GOOD_BODY.replace("https://www.fda.gov/food", "https://mysite.com/food")
    draft = make_draft(body_markdown=body, site_url="https://mysite.com")
    assert rules.get_external_links(draft) == []


def test_is_authority_domain():
    assert rules.is_authority_domain("cdc.gov")
    assert rules.is_authority_domain("en.wikipedia.org")
    assert rules.is_authority_domain("ox.ac.uk")
    assert not rules.is_authority_domain("notwikipedia.org")


def test_external_links_live_with_fake_checker():
    # Fake checkers stand in for the internet, so this test runs offline.
    assert rules.check_external_links_live(make_draft(), link_checker=lambda url: 200).passed
    result = rules.check_external_links_live(make_draft(), link_checker=lambda url: 404)
    assert not result.passed
    assert "404" in result.reason


def test_external_links_live_skipped_without_checker():
    assert rules.check_external_links_live(make_draft()).skipped


def test_internal_links_child_page_must_link_to_main_page():
    main = "https://mysite.com/coffee-guide"
    assert not rules.check_internal_links(make_draft(main_page_url=main)).passed
    body = GOOD_BODY + f"\nSee our [complete coffee guide]({main}).\n"
    assert rules.check_internal_links(make_draft(body_markdown=body, main_page_url=main)).passed


def test_internal_links_main_page_must_link_to_every_child():
    children = ["https://mysite.com/a", "https://mysite.com/b"]
    body = GOOD_BODY + "\nRead the [guide to grinders](https://mysite.com/a).\n"
    result = rules.check_internal_links(make_draft(body_markdown=body, child_page_urls=children))
    assert not result.passed
    assert "https://mysite.com/b" in result.reason


def test_internal_links_skipped_for_standalone_page():
    assert rules.check_internal_links(make_draft()).skipped


def test_descriptive_anchors():
    assert rules.check_descriptive_anchors(make_draft()).passed
    body = GOOD_BODY + "\nFor more, [click here](https://www.fda.gov/x).\n"
    assert not rules.check_descriptive_anchors(make_draft(body_markdown=body)).passed


# --- FAQ ------------------------------------------------------------------------
def test_faq_section_passes():
    assert rules.check_faq_section(make_draft()).passed


def test_faq_section_fails_when_missing():
    body = GOOD_BODY.split("## Frequently Asked Questions")[0]
    assert not rules.check_faq_section(make_draft(body_markdown=body)).passed


def test_faq_section_fails_with_too_few_questions():
    result = rules.check_faq_section(make_draft(), minimum=4)
    assert not result.passed
    assert "3 question" in result.reason


def test_faq_section_fails_when_not_last():
    body = GOOD_BODY + "\n## Final Thoughts\n\nThanks for reading.\n"
    result = rules.check_faq_section(make_draft(body_markdown=body))
    assert not result.passed
    assert "not the last" in result.reason


def test_faq_answers_short_passes_and_fails():
    assert rules.check_faq_answers_short(make_draft()).passed
    long_answer = GOOD_BODY.replace("Clean it once a week.", "word " * 100)
    assert not rules.check_faq_answers_short(make_draft(body_markdown=long_answer)).passed


# --- quality guardrails -----------------------------------------------------
def test_statistics_without_source_fail():
    body = GOOD_BODY.replace("Fresh grounds taste better.", "Fresh grounds taste 45% better.")
    # The FDA link is in the same paragraph, so first prove it passes...
    assert rules.check_statistics_sourced(make_draft(body_markdown=body)).passed
    # ...then put the statistic in its own paragraph with no link.
    body = GOOD_BODY + "\nAbout 1 in 4 people own a grinder.\n"
    assert not rules.check_statistics_sourced(make_draft(body_markdown=body)).passed


def test_audience_reading_level():
    assert rules.check_audience_reading_level(make_draft(body_markdown=long_good_body())).passed
    hard = ("# Coffee Grinder\n\nComprehensive organizational methodologies necessitate "
            "considerable interdepartmental collaboration regarding caffeinated beverage preparation.")
    assert not rules.check_audience_reading_level(make_draft(body_markdown=hard)).passed
    assert rules.check_audience_reading_level(make_draft(audience="")).skipped


def test_get_min_reading_ease_matches_part_of_audience():
    assert rules.get_min_reading_ease("small business owners") == 50
    assert rules.get_min_reading_ease("complete beginners") == 60
    assert rules.get_min_reading_ease("astronauts") == 50   # default


# --- full validation ----------------------------------------------------------
def test_full_valid_blog_passes_every_rule():
    draft = make_draft(body_markdown=long_good_body())
    report = rules.validate_blog(draft, check_links=True, link_checker=lambda url: 200)
    failed = [(r.rule_id, r.reason) for r in report.failed_rules]
    assert report.passed, failed


def test_short_blog_fails_and_report_lists_failures():
    report = rules.validate_blog(make_draft())
    assert not report.passed
    assert "min_word_count" in [r.rule_id for r in report.failed_rules]
    assert "FAIL" in rules.format_report(report)


# --- loading pasted markdown ------------------------------------------------
def test_load_draft_from_markdown_fills_title_and_alt():
    text = "---\nfocus_keyword: coffee grinder\nsecondary_keywords: burr, grind size\n---\n" + GOOD_BODY
    draft = rules.load_draft_from_markdown(text)
    assert draft.title == "How to Choose a Coffee Grinder"
    assert draft.feature_image_alt == "A burr coffee grinder on a table"
    assert draft.secondary_keywords == ["burr", "grind size"]


def test_load_draft_without_keyword_raises_friendly_error():
    try:
        rules.load_draft_from_markdown(GOOD_BODY)
    except rules.BlogInputError as error:
        assert "focus keyword" in str(error).lower()
    else:
        raise AssertionError("Expected BlogInputError")
