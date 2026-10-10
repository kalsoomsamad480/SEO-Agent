"""Write the blog post from the outline, then assemble the final BlogDraft."""

import math
import re

import config
from src.content.internal_links import add_main_page_link
from src.content.outline import bullet_list, outline_to_text
from src.llm.client import LLMClient, get_client, load_prompt
from src.models.schemas import BlogDraft, BlogMetadata, BlogOutline, BlogRequest, KeywordPlan
from src.utils import text_tools as tt
from src.utils.logger import get_logger

logger = get_logger(__name__)

# LLMs often write a bit less than asked, so we aim above the minimum.
EXTRA_WORDS = 300


def keyword_usage_range(focus_keyword: str) -> tuple[int, int]:
    """How many times the writer should use the keyword: (minimum, maximum).

    The maximum keeps density under the limit even if the post is only
    MIN_WORDS long. We take 10% off as a safety margin.
    Example: 2-word keyword, 1000 words, 2% max -> 2% x 1000 / 2 = 10 -> 9 uses.
    """
    keyword_words = max(len(focus_keyword.split()), 1)
    safe_max = math.floor(config.MAX_KEYWORD_DENSITY_PERCENT / 100 * config.MIN_WORDS
                          / keyword_words * 0.9)
    minimum = config.MIN_FOCUS_KEYWORD_COUNT
    return minimum, max(minimum, safe_max)


def _internal_link_rule(request: BlogRequest) -> str:
    """Extra writer instruction when this blog is a child page of a main page."""
    if not request.main_page_url:
        return ""
    anchor = f' (for example "{request.main_page_title}")' if request.main_page_title else ""
    return (f"   Also link once to our main guide at {request.main_page_url} with descriptive "
            f"anchor text that names its topic{anchor}.")


def clean_markdown(reply: str) -> str:
    """Remove ```markdown fences and chatter some models wrap around the article."""
    text = re.sub(r"^```(?:markdown|md)?\s*\n|\n```\s*$", "", reply.strip())
    # Drop anything before the H1 (e.g. "Sure! Here is your article:").
    h1 = re.search(r"^# ", text, flags=re.MULTILINE)
    return text[h1.start():].strip() + "\n" if h1 else text.strip() + "\n"


def write_blog(request: BlogRequest, plan: KeywordPlan, outline: BlogOutline,
               llm: LLMClient | None = None) -> str:
    """Ask the LLM to write the full article in Markdown, following the outline."""
    llm = llm or get_client()
    keyword_min, keyword_max = keyword_usage_range(plan.focus_keyword)
    prompt = load_prompt(
        "write_blog",
        topic=plan.topic,
        audience=request.audience,
        tone=request.tone,
        goal=request.goal,
        focus_keyword=plan.focus_keyword,
        secondary_keywords=", ".join(plan.secondary_keywords) or "(none)",
        outline=outline_to_text(outline),
        h1=outline.h1,
        target_words=config.MIN_WORDS + EXTRA_WORDS,
        min_words=config.MIN_WORDS,
        keyword_min=keyword_min,
        keyword_max=keyword_max,
        authority_links=bullet_list(plan.authority_links),
        internal_link_rule=_internal_link_rule(request),
        faq_questions=bullet_list(outline.faq_questions),
        faq_max_words=config.FAQ_MAX_ANSWER_WORDS,
    )
    logger.info("Writing the article (this can take a minute)...")
    body = clean_markdown(llm.generate_text(prompt, system=load_prompt("system")))
    logger.info("Article written: %d words.", tt.word_count(tt.markdown_to_plain_text(body)))
    return body


def fix_blog(request: BlogRequest, plan: KeywordPlan, body: str, problems: list[str],
             llm: LLMClient | None = None) -> str:
    """Send the article plus the exact rule failures to the LLM and return the corrected article."""
    llm = llm or get_client()
    keyword_min, keyword_max = keyword_usage_range(plan.focus_keyword)
    prompt = load_prompt(
        "fix_blog",
        focus_keyword=plan.focus_keyword,
        secondary_keywords=", ".join(plan.secondary_keywords) or "(none)",
        audience=request.audience,
        tone=request.tone,
        problems=bullet_list(problems),
        min_words=config.MIN_WORDS,
        target_words=config.MIN_WORDS + EXTRA_WORDS,
        keyword_min=keyword_min,
        keyword_max=keyword_max,
        authority_links=bullet_list(plan.authority_links),
        internal_link_rule=_internal_link_rule(request),
        faq_min=config.MIN_FAQ_QUESTIONS,
        faq_max_words=config.FAQ_MAX_ANSWER_WORDS,
        article=body,
    )
    fixed = clean_markdown(llm.generate_text(prompt, system=load_prompt("system")))
    logger.info("Fixed article: %d words.", tt.word_count(tt.markdown_to_plain_text(fixed)))
    return fixed


def insert_feature_image(body: str, alt: str, url: str) -> str:
    """Put the feature image right after the intro paragraph (below the H1)."""
    blocks = body.split("\n\n")
    image = f"![{alt}]({url})"
    h1_index = next((i for i, b in enumerate(blocks) if b.lstrip().startswith("# ")), None)
    if h1_index is None:
        return image + "\n\n" + body
    # After the H1 and its first paragraph, if there is one.
    insert_at = h1_index + 2 if h1_index + 1 < len(blocks) else h1_index + 1
    blocks.insert(insert_at, image)
    return "\n\n".join(blocks)


def assemble_draft(request: BlogRequest, plan: KeywordPlan, body: str,
                   metadata: BlogMetadata) -> BlogDraft:
    """Combine the article and its metadata into one BlogDraft ready for validation.

    We don't generate images, so the image URL is a placeholder file name.
    Replace it with your real image before publishing.
    """
    image_url = f"images/{metadata.slug}.jpg"
    body = insert_feature_image(body, metadata.feature_image_alt, image_url)
    if request.main_page_url:
        # Guarantee the child -> main link in code, even if the LLM forgot it.
        body = add_main_page_link(body, request.main_page_url, request.main_page_title)
    return BlogDraft(
        title=metadata.title,
        meta_description=metadata.meta_description,
        slug=metadata.slug,
        focus_keyword=plan.focus_keyword,
        secondary_keywords=plan.secondary_keywords,
        body_markdown=body,
        feature_image_alt=metadata.feature_image_alt,
        feature_image_url=image_url,
        audience=request.audience,
        site_url=config.SITE_URL,
        main_page_url=request.main_page_url,
    )
