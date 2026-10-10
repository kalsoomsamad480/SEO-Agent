"""Tests for main page <-> child page linking and the site map (temporary folders only)."""

import pytest

import config
from src.agents import pipeline
from src.content import internal_links as il
from src.models.schemas import BlogDraft
from src.publish.exporter import save_blog
from src.validators.seo_rules import validate_blog

BODY = """# Main Topic

Intro.

## Section

Text.

## Frequently Asked Questions

### Question one?

Answer.
"""


@pytest.fixture(autouse=True)
def temp_outputs(monkeypatch, tmp_path):
    """Point the site map and blog folder at a temporary folder for every test."""
    monkeypatch.setattr(config, "SITE_MAP_FILE", tmp_path / "site_map.json")
    monkeypatch.setattr(config, "BLOGS_DIR", tmp_path / "blogs")
    monkeypatch.setattr(config, "SITE_URL", "https://mysite.com")


def make_draft(slug: str, title: str, parent: str | None = None) -> BlogDraft:
    return BlogDraft(title=title, meta_description="d", slug=slug, focus_keyword="topic",
                     body_markdown=BODY, main_page_url=parent)


def test_page_url_uses_site_url():
    assert il.page_url("my-post") == "https://mysite.com/my-post/"


def test_register_and_find_pages():
    il.register_page(make_draft("main", "Main Guide"))
    il.register_page(make_draft("child", "Child Post"), parent_url="https://mysite.com/main/")
    assert il.find_page("main")[1]["title"] == "Main Guide"
    assert il.find_page("https://mysite.com/main")[0] == "main"   # URL without trailing slash
    assert [c["title"] for c in il.children_of("https://mysite.com/main/")] == ["Child Post"]
    assert il.find_page("nope") is None


def test_add_main_page_link_goes_before_faq_with_descriptive_anchor():
    body = il.add_main_page_link(BODY, "https://mysite.com/main/", "Complete Coffee Guide")
    assert "[Complete Coffee Guide](https://mysite.com/main/)" in body
    assert body.index("Complete Coffee Guide") < body.index("## Frequently Asked Questions")


def test_add_main_page_link_does_nothing_if_already_linked():
    body = BODY.replace("Intro.", "See the [coffee guide](https://mysite.com/main).")
    assert il.add_main_page_link(body, "https://mysite.com/main/", "X") == body


def test_set_related_guides_replaces_old_section_instead_of_duplicating():
    one = [{"title": "Child A", "url": "/a/"}]
    two = one + [{"title": "Child B", "url": "/b/"}]
    body = il.set_related_guides(il.set_related_guides(BODY, one), two)
    assert body.count(il.RELATED_HEADING) == 1
    assert "[Child A](/a/)" in body and "[Child B](/b/)" in body
    # The FAQ must stay the last section.
    assert body.index(il.RELATED_HEADING) < body.index("## Frequently Asked Questions")


def test_update_main_page_links_every_child_and_passes_internal_link_rule():
    main = make_draft("main", "Main Guide")
    save_blog(main, validate_blog(main))
    il.register_page(main)
    for slug in ("child-a", "child-b"):
        il.register_page(make_draft(slug, f"Guide {slug}"), parent_url="https://mysite.com/main/")

    folder = il.update_main_page("main")

    saved = (folder / "post.md").read_text(encoding="utf-8")
    assert "[Guide child-a](https://mysite.com/child-a/)" in saved
    assert "[Guide child-b](https://mysite.com/child-b/)" in saved
    report = (folder / "validation_report.json").read_text(encoding="utf-8")
    assert '"rule_id": "internal_links"' in report and "All 2 required internal link(s)" in report


def test_update_main_page_returns_none_for_external_main_page():
    assert il.update_main_page("not-generated-here") is None


def test_sync_site_map_adds_older_blogs():
    old = make_draft("old-post", "Old Post")
    save_blog(old, validate_blog(old))      # saved but never registered
    assert il.sync_site_map() == 1
    assert il.find_page("old-post") is not None


def test_resolve_main_page():
    il.register_page(make_draft("main", "Main Guide"))
    assert pipeline.resolve_main_page("main") == ("https://mysite.com/main/", "Main Guide")
    assert pipeline.resolve_main_page("https://other.com/x") == ("https://other.com/x", "")
    assert pipeline.resolve_main_page("") == ("", "")
    with pytest.raises(ValueError, match="site map"):
        pipeline.resolve_main_page("unknown-slug")


def test_broken_site_map_gives_friendly_error():
    config.SITE_MAP_FILE.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        il.load_site_map()
