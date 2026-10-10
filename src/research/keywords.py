"""Pick the focus keyword and secondary keywords.

Step 1 (code): collect REAL searches from Google autocomplete.
Step 2 (LLM): choose the best focus keyword for the topic and goal.
Step 3 (code): clean up and sanity-check the LLM's choice.
"""

import re
import time

from src.content.outline import bullet_list
from src.llm.client import LLMClient, get_client, load_prompt
from src.models.schemas import BlogRequest, ResearchChoice
from src.research import trends
from src.utils.logger import get_logger

logger = get_logger(__name__)

KEYWORD_PATTERNS = ["{topic}", "how to {topic}", "best {topic}", "{topic} for beginners"]
MAX_IDEAS = 40
MAX_KEYWORD_WORDS = 6
MAX_SECONDARY = 5


def clean_keyword(text: str) -> str:
    """Lowercase, remove punctuation (keep hyphens), and squeeze spaces."""
    text = re.sub(r"[^\w\s-]", " ", text.lower())
    return " ".join(text.split())


def collect_keyword_ideas(topic: str) -> list[str]:
    """Gather real Google autocomplete searches around the topic (no duplicates)."""
    ideas: list[str] = []
    for pattern in KEYWORD_PATTERNS:
        for suggestion in trends.google_autocomplete(pattern.format(topic=topic)):
            cleaned = clean_keyword(suggestion)
            if cleaned and cleaned not in ideas:
                ideas.append(cleaned)
        time.sleep(trends.SMALL_PAUSE_SECONDS)
    logger.info("Collected %d keyword ideas from autocomplete.", len(ideas))
    return ideas[:MAX_IDEAS]


def tidy_choice(choice: ResearchChoice, fallback: str) -> ResearchChoice:
    """Check the LLM's choice in code and repair what we can.

    - The focus keyword must be 1-6 words; otherwise use the fallback (the topic).
    - Secondary keywords: cleaned, no duplicates, not the focus keyword, at most 5.
    - Source URLs: only http(s) links are kept (they are verified later anyway).
    """
    focus = clean_keyword(choice.focus_keyword)
    if not focus or len(focus.split()) > MAX_KEYWORD_WORDS:
        logger.warning("LLM focus keyword '%s' is unusable; using '%s'.", choice.focus_keyword, fallback)
        focus = clean_keyword(fallback)

    secondary: list[str] = []
    for keyword in choice.secondary_keywords:
        keyword = clean_keyword(keyword)
        if keyword and keyword != focus and keyword not in secondary:
            secondary.append(keyword)

    sources = [url.strip() for url in choice.source_suggestions if url.strip().startswith("http")]
    return ResearchChoice(focus_keyword=focus, secondary_keywords=secondary[:MAX_SECONDARY],
                          source_suggestions=sources)


def choose_keywords(request: BlogRequest, ideas: list[str],
                    llm: LLMClient | None = None) -> ResearchChoice:
    """Let the LLM pick the focus + secondary keywords (and suggest sources), then tidy it."""
    llm = llm or get_client()
    prompt = load_prompt(
        "research",
        topic=request.topic,
        niche=request.niche or "(not given)",
        audience=request.audience,
        goal=request.goal,
        keyword_ideas=bullet_list(ideas),
    )
    logger.info("Choosing keywords...")
    choice = llm.generate_json(prompt, ResearchChoice, system=load_prompt("system"))
    choice = tidy_choice(choice, fallback=request.topic)
    logger.info("Focus keyword: '%s' | secondary: %s", choice.focus_keyword,
                ", ".join(choice.secondary_keywords) or "(none)")
    return choice
