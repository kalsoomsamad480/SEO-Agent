"""Tests for the content steps (outline, writer, metadata) with a fake LLM."""

from src.content import metadata, outline, writer
from src.models.schemas import BlogMetadata, BlogOutline, BlogRequest, KeywordPlan, OutlineSection

REQUEST = BlogRequest(topic="Coffee grinders", audience="beginners")
PLAN = KeywordPlan(topic="Coffee grinders", focus_keyword="coffee grinder",
                   faq_questions=["Is it worth it?"], authority_links=["https://www.fda.gov/food"])


class FakeLLM:
    """Returns pre-written answers instead of calling a real AI, and records the prompts."""

    def __init__(self, text: str = "", json_objects: list | None = None):
        self.text = text
        self.json_objects = list(json_objects or [])
        self.prompts: list[str] = []

    def generate_text(self, prompt, system=None, temperature=0.7):
        self.prompts.append(prompt)
        return self.text

    def generate_json(self, prompt, schema, system=None):
        self.prompts.append(prompt)
        return self.json_objects.pop(0)


def test_create_outline_adds_missing_question_marks():
    fake = FakeLLM(json_objects=[BlogOutline(
        h1="Coffee Grinder Guide", intro_notes="intro",
        sections=[OutlineSection(h2="Why a Coffee Grinder Matters")],
        faq_questions=["Is it worth it", "How do I clean it?"],
    )])
    result = outline.create_outline(REQUEST, PLAN, llm=fake)
    assert result.faq_questions == ["Is it worth it?", "How do I clean it?"]
    assert "coffee grinder" in fake.prompts[0]


def test_write_blog_strips_code_fences_and_chatter():
    fake = FakeLLM(text="Sure! Here it is:\n```markdown\n# Coffee Grinder Guide\n\nText.\n```")
    out = BlogOutline(h1="Coffee Grinder Guide", intro_notes="", sections=[], faq_questions=["Q?"])
    body = writer.write_blog(REQUEST, PLAN, out, llm=fake)
    assert body.startswith("# Coffee Grinder Guide")
    assert "```" not in body
    assert "https://www.fda.gov/food" in fake.prompts[0]   # sources are passed to the writer


def test_keyword_usage_range_keeps_density_safe():
    minimum, maximum = writer.keyword_usage_range("coffee grinder")
    assert minimum == 5
    assert maximum == 9   # 2% of 1000 words / 2 words = 10, minus 10% margin


def test_insert_feature_image_goes_after_intro():
    body = "# Title\n\nIntro paragraph.\n\n## Section\n\nText."
    result = writer.insert_feature_image(body, "alt text", "img.jpg")
    assert result == "# Title\n\nIntro paragraph.\n\n![alt text](img.jpg)\n\n## Section\n\nText."


def test_fix_slug():
    assert metadata.fix_slug("Best Coffee Grinder 2026!", "coffee grinder") == "best-coffee-grinder-2026"
    assert metadata.fix_slug("grinder-guide", "coffee grinder") == "coffee-grinder"


def test_create_metadata_retries_when_rules_broken():
    bad = BlogMetadata(title="x" * 70, meta_description="no keyword", slug="s", feature_image_alt="photo")
    good = BlogMetadata(title="Coffee Grinder Guide", meta_description="A coffee grinder guide.",
                        slug="coffee-grinder-guide", feature_image_alt="A coffee grinder on a table")
    fake = FakeLLM(json_objects=[bad, good])
    result = metadata.create_metadata(REQUEST, PLAN, "# Coffee Grinder Guide\n\nIntro.", llm=fake)
    assert result == good
    assert "broke these rules" in fake.prompts[1]


def test_assemble_draft_includes_image_and_metadata():
    meta = BlogMetadata(title="T", meta_description="M", slug="coffee-grinder", feature_image_alt="A coffee grinder")
    draft = writer.assemble_draft(REQUEST, PLAN, "# H1\n\nIntro.\n\n## A\n\nText.", meta)
    assert "![A coffee grinder](images/coffee-grinder.jpg)" in draft.body_markdown
    assert draft.focus_keyword == "coffee grinder"
