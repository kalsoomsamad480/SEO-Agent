"""Find REAL questions people ask, for the FAQ section.

We type question starters ("what is ...", "how do I ...") plus the keyword
into Google autocomplete and keep the suggestions that are questions.
The LLM then picks the most useful ones, and code checks that every
picked question really came from that list (no invented questions).
"""

import time
from difflib import SequenceMatcher

import config
from src.content.outline import bullet_list
from src.llm.client import LLMClient, get_client, load_prompt
from src.models.schemas import BlogRequest, FaqChoice
from src.research import trends
from src.utils.logger import get_logger

logger = get_logger(__name__)

QUESTION_STARTERS = ["what is", "how to", "how do i", "why", "can i", "is"]
QUESTION_WORDS = ("what", "how", "why", "can", "is", "are", "do", "does", "should",
                  "which", "when", "where", "who", "will")
TARGET_FAQ_COUNT = 5
MIN_SIMILARITY = 0.6   # how close a picked question must be to a real one (0-1)


def as_question(text: str) -> str:
    """Format a search as a question: capital first letter, ends with "?"."""
    text = text.strip().rstrip("?").strip()
    return text[:1].upper() + text[1:] + "?"


def collect_questions(keyword: str) -> list[str]:
    """Return real autocomplete searches about the keyword that are questions."""
    questions: list[str] = []
    for starter in QUESTION_STARTERS:
        for suggestion in trends.google_autocomplete(f"{starter} {keyword}"):
            if suggestion.lower().startswith(QUESTION_WORDS):
                question = as_question(suggestion)
                if question not in questions:
                    questions.append(question)
        time.sleep(trends.SMALL_PAUSE_SECONDS)
    logger.info("Found %d real questions about '%s'.", len(questions), keyword)
    return questions


def is_close_to_any(question: str, real_questions: list[str]) -> bool:
    """True if the question is (almost) the same as one of the real questions."""
    return any(SequenceMatcher(None, question.lower(), real.lower()).ratio() >= MIN_SIMILARITY
               for real in real_questions)


def choose_faq_questions(request: BlogRequest, keyword: str, questions: list[str],
                         llm: LLMClient | None = None,
                         count: int = TARGET_FAQ_COUNT) -> list[str]:
    """Pick the best `count` questions. Uses the LLM only when there are more than we need."""
    if len(questions) < config.MIN_FAQ_QUESTIONS:
        logger.warning("Only %d real question(s) found; the outline step will add related ones.",
                       len(questions))
    if len(questions) <= count:
        return questions

    llm = llm or get_client()
    prompt = load_prompt("faq", focus_keyword=keyword, audience=request.audience,
                         questions=bullet_list(questions), count=count)
    choice = llm.generate_json(prompt, FaqChoice, system=load_prompt("system"))

    # Keep only questions that really came from the list.
    picked = [as_question(q) for q in choice.questions if is_close_to_any(q, questions)]
    # If the LLM picked too few valid ones, top up with real questions in their original order.
    for question in questions:
        if len(picked) >= count:
            break
        if question not in picked:
            picked.append(question)
    return picked[:count]
