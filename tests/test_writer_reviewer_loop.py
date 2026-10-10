"""Tests for the writer <-> reviewer loop, with a fake LLM (offline, free)."""

from src.agents.writer_reviewer_loop import run_writer_reviewer_loop
from src.models.schemas import BlogMetadata, BlogOutline, BlogRequest, KeywordPlan

REQUEST = BlogRequest(topic="Coffee grinders", audience="beginners")
PLAN = KeywordPlan(topic="Coffee grinders", focus_keyword="coffee grinder",
                   authority_links=["https://www.fda.gov/food"])
OUTLINE = BlogOutline(h1="How to Choose a Coffee Grinder", intro_notes="", sections=[],
                      faq_questions=["Is a coffee grinder worth it?"])
GOOD_META = BlogMetadata(title="Coffee Grinder Guide for Beginners",
                         meta_description="Learn how to choose a coffee grinder with this simple guide.",
                         slug="coffee-grinder-guide",
                         feature_image_alt="A burr coffee grinder on a kitchen table")

FILLER = "You can start small and learn as you go. Taste each cup and write down what you like. " * 20
FAQ = """## Frequently Asked Questions

### Is a coffee grinder worth it?

Yes. Fresh coffee tastes better.

### How often should I clean it?

Clean it once a week.

### Can I grind spices in it?

Use a separate grinder for spices.
"""
GOOD_ARTICLE = f"""# How to Choose a Coffee Grinder

A coffee grinder helps you make fresher coffee at home. {FILLER}

## Why a Coffee Grinder Matters

{FILLER} The [FDA food safety guide](https://www.fda.gov/food) explains how to store food well.

## How to Use Your New Grinder

{FILLER} Clean your coffee grinder often. A good coffee grinder lasts for years.

{FAQ}"""
SHORT_ARTICLE = "# How to Choose a Coffee Grinder\n\nA coffee grinder is useful.\n\n## Tips\n\nShort text.\n"


class FakeLLM:
    """Returns the given articles in order (first = written draft, then each fix)."""

    def __init__(self, articles: list[str]):
        self.articles = list(articles)
        self.text_prompts: list[str] = []
        self.json_calls = 0

    def generate_text(self, prompt, system=None, temperature=0.7):
        self.text_prompts.append(prompt)
        # Keep returning the last article if the loop asks for more.
        return self.articles.pop(0) if len(self.articles) > 1 else self.articles[0]

    def generate_json(self, prompt, schema, system=None):
        self.json_calls += 1
        return GOOD_META


def always_200(url: str) -> int:
    return 200


def test_good_first_draft_needs_no_fix_rounds():
    fake = FakeLLM([GOOD_ARTICLE])
    result = run_writer_reviewer_loop(REQUEST, PLAN, OUTLINE, llm=fake, link_checker=always_200)
    assert result.report.passed, [r.reason for r in result.report.failed_rules]
    assert result.fix_rounds_used == 0
    assert len(fake.text_prompts) == 1   # only the first write, no fix call


def test_failing_draft_is_fixed_in_one_round():
    fake = FakeLLM([SHORT_ARTICLE, GOOD_ARTICLE])
    result = run_writer_reviewer_loop(REQUEST, PLAN, OUTLINE, llm=fake, link_checker=always_200)
    assert result.report.passed
    assert result.fix_rounds_used == 1
    # The fix prompt must contain the exact failure reasons from the validator.
    fix_prompt = fake.text_prompts[1]
    assert "PROBLEMS TO FIX" in fix_prompt
    assert "words" in fix_prompt and "short" in fix_prompt


def test_loop_stops_after_max_rounds_and_keeps_best_draft():
    # Gets a bit better, then worse again: the loop must keep the better middle version.
    almost = GOOD_ARTICLE.replace("Can I grind spices in it?", "Spices")   # only 2 FAQ questions
    fake = FakeLLM([SHORT_ARTICLE, almost, SHORT_ARTICLE, SHORT_ARTICLE])
    result = run_writer_reviewer_loop(REQUEST, PLAN, OUTLINE, llm=fake, max_rounds=3,
                                      link_checker=always_200)
    assert not result.report.passed
    assert result.fix_rounds_used == 3
    assert len(fake.text_prompts) == 4          # 1 write + 3 fixes, never more
    assert [r.rule_id for r in result.report.failed_rules] == ["faq_section"]
    assert len(result.history) == 4


def test_broken_link_is_reported_to_the_fixer():
    def fda_is_down(url: str) -> int:
        return 404
    fake = FakeLLM([GOOD_ARTICLE])
    result = run_writer_reviewer_loop(REQUEST, PLAN, OUTLINE, llm=fake, max_rounds=1,
                                      link_checker=fda_is_down)
    assert "external_links_live" in [r.rule_id for r in result.report.failed_rules]
    assert "404" in fake.text_prompts[1]


def test_metadata_failure_regenerates_metadata_only_when_needed():
    fake = FakeLLM([GOOD_ARTICLE])
    run_writer_reviewer_loop(REQUEST, PLAN, OUTLINE, llm=fake, link_checker=always_200)
    assert fake.json_calls == 1   # metadata was fine, so it was created only once
