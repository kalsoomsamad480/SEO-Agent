"""Tests for the research tools. All network calls are replaced with fakes."""

import pytest

from src.agents import pipeline
from src.models.schemas import BlogRequest, FaqChoice, ResearchChoice, TopicIdea
from src.research import authority_links, faq_finder, keywords, trends

REQUEST = BlogRequest(topic="coffee grinders", audience="beginners")


@pytest.fixture(autouse=True)
def no_pauses(monkeypatch):
    monkeypatch.setattr(trends, "SMALL_PAUSE_SECONDS", 0)


def fake_autocomplete(monkeypatch, answers: dict[str, list[str]]):
    """Make google_autocomplete return canned suggestions (empty list for unknown queries)."""
    monkeypatch.setattr(trends, "google_autocomplete", lambda query: answers.get(query, []))


class FakeLLM:
    def __init__(self, reply):
        self.reply = reply

    def generate_json(self, prompt, schema, system=None):
        return self.reply


# --- trends ---------------------------------------------------------------------
def test_relevance_score():
    assert trends.relevance_score("web development course", "web development") == 1.0
    assert trends.relevance_score("web hosting", "web development") == 0.5
    assert trends.relevance_score("cooking", "web development") == 0.0


def test_clean_and_rank_removes_junk_and_sorts():
    ideas = [TopicIdea(topic=t, source="test") for t in [
        "web hosting tips",                      # 0.5
        "web development nixcoders.org",         # website spam -> removed
        "web development",                       # the bare niche -> removed
        "learn web development",                 # 1.0
        "Learn Web Development",                 # duplicate -> removed
    ]]
    ranked = trends.clean_and_rank(ideas, "web development")
    assert [i.topic for i in ranked] == ["learn web development", "web hosting tips"]


def test_find_topics_falls_back_to_autocomplete_when_trends_fail(monkeypatch):
    def broken_trends(niche):
        raise ConnectionError("Google said no")
    monkeypatch.setattr(trends, "fetch_google_trends", broken_trends)
    fake_autocomplete(monkeypatch, {"coffee": ["coffee grinder guide", "coffee beans"]})
    topics = trends.find_topics("coffee")
    assert [t.topic for t in topics] == ["coffee grinder guide", "coffee beans"]


def test_find_topics_raises_friendly_error_when_nothing_found(monkeypatch):
    monkeypatch.setattr(trends, "fetch_google_trends", lambda niche: [])
    fake_autocomplete(monkeypatch, {})
    with pytest.raises(trends.ResearchError):
        trends.find_topics("coffee")


# --- keywords ---------------------------------------------------------------------
def test_clean_keyword():
    assert keywords.clean_keyword("  Best Coffee-Grinder, 2026! ") == "best coffee-grinder 2026"


def test_tidy_choice_cleans_and_dedupes():
    choice = ResearchChoice(
        focus_keyword="Coffee Grinder",
        secondary_keywords=["burr grinder", "coffee grinder", "Burr Grinder", "grind size"],
        source_suggestions=["https://www.fda.gov/food", "not a url"],
    )
    tidy = keywords.tidy_choice(choice, fallback="coffee grinders")
    assert tidy.focus_keyword == "coffee grinder"
    assert tidy.secondary_keywords == ["burr grinder", "grind size"]
    assert tidy.source_suggestions == ["https://www.fda.gov/food"]


def test_tidy_choice_falls_back_when_keyword_is_too_long():
    choice = ResearchChoice(focus_keyword="this keyword is far far too long to be useful")
    assert keywords.tidy_choice(choice, fallback="Coffee Grinders").focus_keyword == "coffee grinders"


def test_collect_keyword_ideas(monkeypatch):
    fake_autocomplete(monkeypatch, {"coffee grinders": ["Coffee Grinders", "coffee grinders uk"],
                                    "best coffee grinders": ["best coffee grinders 2026"]})
    assert keywords.collect_keyword_ideas("coffee grinders") == [
        "coffee grinders", "coffee grinders uk", "best coffee grinders 2026"]


# --- FAQ questions ------------------------------------------------------------------
def test_collect_questions_keeps_only_questions(monkeypatch):
    fake_autocomplete(monkeypatch, {
        "what is coffee grinder": ["what is a coffee grinder", "coffee grinder price"],
        "how to coffee grinder": ["how to clean a coffee grinder"],
    })
    assert faq_finder.collect_questions("coffee grinder") == [
        "What is a coffee grinder?", "How to clean a coffee grinder?"]


def test_choose_faq_rejects_invented_questions():
    real = [f"How do I clean grinder model {n}?" for n in range(1, 8)]
    llm = FakeLLM(FaqChoice(questions=["How do I clean grinder model 3?",
                                       "What is the meaning of life?"]))   # invented
    picked = faq_finder.choose_faq_questions(REQUEST, "grinder", real, llm=llm, count=3)
    assert picked[0] == "How do I clean grinder model 3?"
    assert "What is the meaning of life?" not in picked
    assert len(picked) == 3   # topped up with real questions


def test_choose_faq_skips_llm_when_few_questions():
    questions = ["What is a coffee grinder?", "Is a grinder worth it?"]
    assert faq_finder.choose_faq_questions(REQUEST, "x", questions, llm=None) == questions


# --- authority links -----------------------------------------------------------------
def test_mentions_topic():
    assert authority_links.mentions_topic("all about the coffee grinder", "coffee grinder")
    assert not authority_links.mentions_topic("a page about tea", "coffee grinder")


def test_verify_source_checks_domain_status_and_topic(monkeypatch):
    pages = {"https://www.fda.gov/coffee": (200, "coffee grinder safety"),
             "https://www.fda.gov/missing": (404, ""),
             "https://www.fda.gov/tea": (200, "tea only")}
    monkeypatch.setattr(authority_links, "fetch_page", lambda url: pages[url])
    assert authority_links.verify_source("https://www.fda.gov/coffee", "coffee grinder")
    assert not authority_links.verify_source("https://www.fda.gov/missing", "coffee grinder")
    assert not authority_links.verify_source("https://www.fda.gov/tea", "coffee grinder")
    assert not authority_links.verify_source("https://random-blog.example/x", "coffee grinder")


def test_find_authority_links_uses_wikipedia_when_suggestions_fail(monkeypatch):
    wiki = "https://en.wikipedia.org/wiki/Coffee_grinder"
    monkeypatch.setattr(authority_links, "search_wikipedia", lambda query, limit=3: [wiki])
    monkeypatch.setattr(authority_links, "fetch_page",
                        lambda url: (200, "coffee grinder") if url == wiki else (404, ""))
    links = authority_links.find_authority_links("coffee grinder", ["https://www.fda.gov/invented"])
    assert links == [wiki]


# --- manual mode answers ------------------------------------------------------------
def test_parse_goal():
    assert pipeline.parse_goal("3") == "sales"
    assert pipeline.parse_goal("get leads") == "leads"
    assert pipeline.parse_goal("rank for a keyword") == "rank"
    assert pipeline.parse_goal("") == "educate"


def test_build_request_defaults_and_validation():
    request = pipeline.build_request("Coffee grinders", "", "1")
    assert request.audience == "beginners"
    assert request.tone == pipeline.DEFAULT_TONE
    assert request.main_page_url is None
    with pytest.raises(ValueError):
        pipeline.build_request("  ", "beginners", "1")
