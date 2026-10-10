"""Create the blog outline (the plan) before writing.

Why outline first? A writer with a plan produces a better structure, and we
can make sure the focus keyword lands in the H1 and an H2 before a single
paragraph is written.
"""

import config
from src.llm.client import LLMClient, get_client, load_prompt
from src.models.schemas import BlogOutline, BlogRequest, KeywordPlan
from src.utils.logger import get_logger

logger = get_logger(__name__)


def bullet_list(items: list[str]) -> str:
    """Format a list as "- item" lines for a prompt ("- (none)" if empty)."""
    return "\n".join(f"- {item}" for item in items) or "- (none)"


def create_outline(request: BlogRequest, plan: KeywordPlan,
                   llm: LLMClient | None = None) -> BlogOutline:
    """Ask the LLM for a structured outline (H1, H2 sections, FAQ questions)."""
    llm = llm or get_client()
    # Ask for at least the minimum number of FAQ questions, but no more than 5.
    faq_count = max(config.MIN_FAQ_QUESTIONS, min(5, len(plan.faq_questions)))
    prompt = load_prompt(
        "outline",
        topic=plan.topic,
        audience=request.audience,
        tone=request.tone,
        goal=request.goal,
        focus_keyword=plan.focus_keyword,
        secondary_keywords=", ".join(plan.secondary_keywords) or "(none)",
        faq_questions=bullet_list(plan.faq_questions),
        faq_count=faq_count,
    )
    logger.info("Creating outline for '%s'...", plan.focus_keyword)
    outline = llm.generate_json(prompt, BlogOutline, system=load_prompt("system"))

    # FAQ questions must end with "?" for the validator to recognise them.
    outline.faq_questions = [q.strip().rstrip(".") + ("" if q.strip().endswith("?") else "?")
                             for q in outline.faq_questions]
    logger.info("Outline ready: %d sections, %d FAQ questions.",
                len(outline.sections), len(outline.faq_questions))
    return outline


def outline_to_text(outline: BlogOutline) -> str:
    """Turn the outline into readable Markdown-like text to put inside the writer prompt."""
    lines = [f"# {outline.h1}", f"(Intro: {outline.intro_notes})"]
    for section in outline.sections:
        lines.append(f"## {section.h2}")
        if section.notes:
            lines.append(f"(Cover: {section.notes})")
        lines.extend(f"### {h3}" for h3 in section.h3s)
    return "\n".join(lines)
