"""Tests for src/publish/exporter.py (writes to a temporary folder only)."""

import json

import config
from src.models.schemas import BlogDraft
from src.publish import exporter
from src.validators.seo_rules import load_draft_from_markdown, validate_blog

DRAFT = BlogDraft(
    title='Coffee Grinder Guide: "Burr" vs <Blade>',
    meta_description="Learn how to choose a coffee grinder.",
    slug="coffee-grinder-guide",
    focus_keyword="coffee grinder",
    secondary_keywords=["burr grinder"],
    body_markdown=("# Coffee Grinder Guide\n\nIntro with a [source](https://www.fda.gov/food).\n\n"
                   "## Frequently Asked Questions\n\n### Is it worth it?\n\nYes, **definitely**.\n"),
    feature_image_alt="A coffee grinder",
    feature_image_url="images/coffee-grinder-guide.jpg",
    audience="beginners",
    site_url="https://mysite.com",
)


def test_save_blog_writes_all_four_files(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "BLOGS_DIR", tmp_path)
    folder = exporter.save_blog(DRAFT, validate_blog(DRAFT))
    names = sorted(p.name for p in folder.iterdir())
    assert names == ["meta.json", "post.html", "post.md", "validation_report.json"]
    assert json.loads((folder / "meta.json").read_text())["slug"] == "coffee-grinder-guide"


def test_post_md_round_trips_through_the_validator_loader(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "BLOGS_DIR", tmp_path)
    folder = exporter.save_blog(DRAFT, validate_blog(DRAFT))
    loaded = load_draft_from_markdown((folder / "post.md").read_text(encoding="utf-8"))
    assert loaded.model_dump() == DRAFT.model_dump()


def test_html_has_escaped_title_meta_and_canonical():
    page = exporter.build_html(DRAFT)
    assert "<title>Coffee Grinder Guide: &quot;Burr&quot; vs &lt;Blade&gt;</title>" in page
    assert '<meta name="description" content="Learn how to choose a coffee grinder.">' in page
    assert '<link rel="canonical" href="https://mysite.com/coffee-grinder-guide/">' in page
    assert "<h1>Coffee Grinder Guide</h1>" in page
    assert "Human review required" in page


def test_structured_data_includes_faq_answers_as_plain_text():
    blocks = exporter.build_structured_data(DRAFT)
    assert blocks[0]["@type"] == "BlogPosting"
    faq = blocks[1]
    assert faq["@type"] == "FAQPage"
    assert faq["mainEntity"][0]["name"] == "Is it worth it?"
    assert faq["mainEntity"][0]["acceptedAnswer"]["text"] == "Yes, definitely."


def test_no_faq_means_no_faq_structured_data():
    draft = DRAFT.model_copy(update={"body_markdown": "# Title\n\nText."})
    assert [b["@type"] for b in exporter.build_structured_data(draft)] == ["BlogPosting"]
