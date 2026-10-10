"""Tests for the off-page (backlink) assistant: tracker, opportunities and drafts. Offline."""

import json
from pathlib import Path

import pytest

import config
from src.models.schemas import Opportunity
from src.offpage import opportunities as opp
from src.offpage import outreach, tracker


@pytest.fixture(autouse=True)
def temp_outputs(monkeypatch, tmp_path):
    """Use a temporary tracker and outreach folder for every test."""
    monkeypatch.setattr(config, "TRACKER_FILE", tmp_path / "tracker.csv")
    monkeypatch.setattr(config, "OUTREACH_DIR", tmp_path / "outreach")
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(opp, "SEARCH_PAUSE_SECONDS", 0)


def item(url="https://site.com/write-for-us", status="found", category="guest_post", relevance=0.9):
    return Opportunity(id=tracker.make_id(url, "blog"), opportunity="Site", category=category,
                       url=url, relevance=relevance, status=status, blog_slug="blog")


# --- tracker --------------------------------------------------------------------
def test_tracker_round_trip_and_no_duplicates():
    assert tracker.add_opportunities([item()]) != []
    assert tracker.add_opportunities([item()]) == []          # same url + blog -> skipped
    rows = tracker.load_tracker()
    assert len(rows) == 1 and rows[0].url == "https://site.com/write-for-us"


def test_status_must_follow_the_human_review_flow():
    tracker.add_opportunities([item()])
    item_id = tracker.load_tracker()[0].id
    with pytest.raises(ValueError, match="Can't move"):
        tracker.update_item(item_id, status="sent")         # can't skip draft + approval
    tracker.update_item(item_id, status="draft")
    with pytest.raises(ValueError, match="Can't move"):
        tracker.update_item(item_id, status="sent")         # still needs approval
    tracker.update_item(item_id, status="approved")
    assert tracker.update_item(item_id, status="sent").status == "sent"
    with pytest.raises(ValueError, match="final"):
        tracker.update_item(item_id, status="draft")        # sent is final


def test_unknown_id_gives_friendly_error():
    with pytest.raises(ValueError, match="No opportunity"):
        tracker.update_item("nope", status="draft")


def test_make_id_is_stable():
    assert tracker.make_id("https://a.com", "x") == tracker.make_id("https://a.com", "x")
    assert tracker.make_id("https://a.com", "x") != tracker.make_id("https://a.com", "y")


# --- opportunities ------------------------------------------------------------------
def test_relevance():
    assert opp.relevance("Web development blog - write for us", ["web development"]) == 1.0
    assert opp.relevance("Cooking recipes", ["web development"]) == 0.0


def test_platforms_match_the_niche():
    names = {i.opportunity for i in opp.platform_opportunities("web development", "blog")}
    assert "DEV Community" in names          # made for developers
    assert "Medium (profile + posts)" in names   # fits any niche
    assert "SoundCloud" not in names          # music platform, wrong niche


def test_paid_links_and_social_sites_are_rejected():
    assert opp.is_acceptable_result({"url": "https://blog.com/", "title": "Write for us"})
    assert not opp.is_acceptable_result({"url": "https://x.com/", "title": "Buy backlinks cheap"})
    assert not opp.is_acceptable_result({"url": "https://seo.com/", "title": "Guest post service, $50"})
    assert not opp.is_acceptable_result({"url": "https://www.reddit.com/r/x", "title": "web dev"})


def test_search_opportunities_with_fake_search():
    results = [
        {"url": "https://webdevblog.com/write-for-us", "title": "Web development blog: write for us",
         "description": "We accept <strong>guest posts</strong> about web development."},
        {"url": "https://links4sale.com/", "title": "Buy backlinks for web development", "description": ""},
        {"url": "https://gardening.com/contribute", "title": "Gardening tips", "description": "Plants"},
    ]
    items = opp.search_opportunities({"guest_post": ["q"]}, ["web development"], "blog",
                                     search=lambda query: results)
    assert [i.url for i in items] == ["https://webdevblog.com/write-for-us"]
    assert "<strong>" not in items[0].notes


def test_find_opportunities_without_key_returns_platforms_and_queries(monkeypatch):
    monkeypatch.setattr(config, "BRAVE_SEARCH_API_KEY", "")
    items, queries = opp.find_opportunities("web development", "web development courses", "blog")
    assert items and all(i.category in opp.CATEGORIES for i in items)
    assert 'web development "write for us"' in queries["guest_post"]
    assert items == sorted(items, key=lambda i: i.relevance, reverse=True)


# --- outreach drafts ----------------------------------------------------------------
class FakeLLM:
    def __init__(self):
        self.prompts = []

    def generate_text(self, prompt, system=None, temperature=0.7):
        self.prompts.append(prompt)
        return "Subject: Article idea\n\nHi [name], ..."


def write_blog_folder(tmp_path: Path) -> Path:
    folder = tmp_path / "blogs" / "web-courses"
    folder.mkdir(parents=True)
    (folder / "meta.json").write_text(json.dumps({
        "title": "Web Courses", "slug": "web-courses", "focus_keyword": "web development courses",
        "meta_description": "A guide to courses."}), encoding="utf-8")
    return folder


def test_create_drafts_saves_files_marks_draft_and_never_sends(tmp_path):
    blog = outreach.load_blog(write_blog_folder(tmp_path))
    rows = [item("https://a.com/w", relevance=0.9), item("https://b.com/w", relevance=0.5),
            item("https://c.com/w", status="approved")]
    tracker.add_opportunities(rows)
    fake = FakeLLM()

    paths = outreach.create_drafts(tracker.load_tracker(), blog, max_drafts=1, llm=fake)

    assert len(paths) == 1                                  # respects max_drafts
    text = paths[0].read_text(encoding="utf-8")
    assert text.startswith("DRAFT - NOT SENT")
    statuses = {r.url: r.status for r in tracker.load_tracker()}
    assert statuses == {"https://a.com/w": "draft", "https://b.com/w": "found",
                        "https://c.com/w": "approved"}      # only "found" items get drafted
    assert "Web Courses" in fake.prompts[0] and "https://a.com/w" in fake.prompts[0]


def test_load_blog_with_wrong_folder_gives_friendly_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="meta.json"):
        outreach.load_blog(tmp_path)


def test_offpage_code_contains_no_sending_or_posting():
    """Guardrail: the off-page module may only GET search results. No POST, SMTP or browser bots."""
    source = "".join(Path(f"src/offpage/{name}.py").read_text(encoding="utf-8")
                     for name in ("opportunities", "outreach", "tracker"))
    for forbidden in ("requests.post", "smtplib", "selenium", "playwright", "captcha"):
        assert forbidden not in source.lower()
