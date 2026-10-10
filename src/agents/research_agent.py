"""The research step: turns a BlogRequest into a KeywordPlan.

It uses four "tools" in a fixed order:
    1. keyword ideas      (Google autocomplete - code)
    2. keyword choice     (LLM picks, code checks)
    3. real FAQ questions (Google autocomplete - code, LLM picks the best)
    4. authority sources  (LLM suggests + Wikipedia, code verifies each one)

A fixed order is simpler and more predictable than letting the LLM decide
which tool to call next. docs/architecture.md explains how this could later
become a LangGraph agent that chooses its own steps.
"""

from src.llm.client import LLMClient, get_client
from src.models.schemas import BlogRequest, KeywordPlan
from src.research import authority_links, faq_finder, keywords
from src.utils.logger import get_logger

logger = get_logger(__name__)


def research(request: BlogRequest, llm: LLMClient | None = None) -> KeywordPlan:
    """Run all research tools and return the plan the writer will follow."""
    llm = llm or get_client()
    logger.info("Researching '%s'...", request.topic)

    ideas = keywords.collect_keyword_ideas(request.topic)
    choice = keywords.choose_keywords(request, ideas, llm=llm)

    questions = faq_finder.collect_questions(choice.focus_keyword)
    faq_questions = faq_finder.choose_faq_questions(request, choice.focus_keyword, questions, llm=llm)

    sources = authority_links.find_authority_links(
        choice.focus_keyword, choice.source_suggestions, topic=request.topic)

    plan = KeywordPlan(
        topic=request.topic,
        focus_keyword=choice.focus_keyword,
        secondary_keywords=choice.secondary_keywords,
        faq_questions=faq_questions,
        authority_links=sources,
    )
    logger.info("Research done: keyword '%s', %d FAQ questions, %d verified source(s).",
                plan.focus_keyword, len(plan.faq_questions), len(plan.authority_links))
    return plan
