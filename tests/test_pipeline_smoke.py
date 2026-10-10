"""Smoke test: run the WHOLE pipeline offline with a fake LLM and fake internet.

"Smoke test" = turn it on and check nothing catches fire. It doesn't test
every detail; it proves all the parts connect and a blog gets saved.
"""

import json

import config
from src.agents import pipeline
from src.models.schemas import (BlogMetadata, BlogOutline, FaqChoice, OutlineSection,
                                ResearchChoice)
from src.research import authority_links, trends
from tests.test_writer_reviewer_loop import GOOD_ARTICLE

WIKI = "https://en.wikipedia.org/wiki/Coffee_grinder"


class FakeLLM:
    """Answers each kind of request with a fixed, valid response."""

    def __init__(self):
        self.calls: list[str] = []

    def generate_text(self, prompt, system=None, temperature=0.7):
        self.calls.append("text")
        return GOOD_ARTICLE

    def generate_json(self, prompt, schema, system=None):
        self.calls.append(schema.__name__)
        answers = {
            ResearchChoice: ResearchChoice(focus_keyword="Coffee Grinder",
                                           secondary_keywords=["fresh coffee"],
                                           source_suggestions=["https://www.fda.gov/made-up"]),
            FaqChoice: FaqChoice(questions=["Is a coffee grinder worth it?"]),
            BlogOutline: BlogOutline(h1="How to Choose a Coffee Grinder", intro_notes="",
                                     sections=[OutlineSection(h2="Why a Coffee Grinder Matters")],
                                     faq_questions=["Is a coffee grinder worth it?"]),
            BlogMetadata: BlogMetadata(title="Coffee Grinder Guide for Beginners",
                                       meta_description="Learn how to choose a coffee grinder.",
                                       slug="coffee-grinder-guide",
                                       feature_image_alt="A burr coffee grinder on a table"),
        }
        return answers[schema]


def test_full_pipeline_runs_offline_and_saves_blog(monkeypatch, tmp_path):
    # Fake internet: autocomplete, Wikipedia and page downloads.
    monkeypatch.setattr(trends, "SMALL_PAUSE_SECONDS", 0)
    monkeypatch.setattr(trends, "google_autocomplete",
                        lambda query: ["coffee grinder", "is a coffee grinder worth it"])
    monkeypatch.setattr(authority_links, "search_wikipedia", lambda query, limit=3: [WIKI])
    monkeypatch.setattr(authority_links, "fetch_page",
                        lambda url: (200, "coffee grinder") if url == WIKI else (404, ""))
    # Save into a temporary folder instead of the real outputs/.
    monkeypatch.setattr(config, "BLOGS_DIR", tmp_path)
    monkeypatch.setattr(config, "SITE_MAP_FILE", tmp_path / "site_map.json")

    request = pipeline.build_request("coffee grinders", "beginners", "1")
    progress_messages: list[str] = []
    result = pipeline.run_pipeline(request, llm=FakeLLM(), link_checker=lambda url: 200,
                                   on_progress=progress_messages.append)

    # Research: keyword cleaned, invented source rejected, Wikipedia verified.
    assert result.plan.focus_keyword == "coffee grinder"
    assert result.plan.authority_links == [WIKI]
    # Writing + review: the article passes every rule.
    assert result.report.passed, [r.reason for r in result.report.failed_rules]
    # Export: the files exist.
    assert result.folder == tmp_path / "coffee-grinder-guide"
    for name in ("post.md", "meta.json", "validation_report.json"):
        assert (result.folder / name).is_file()
    assert json.loads((result.folder / "validation_report.json").read_text())["passed"] is True
    assert len(progress_messages) == 4
