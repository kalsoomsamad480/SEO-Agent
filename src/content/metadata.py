"""Create the title tag, meta description, URL slug and image alt text.

All four reuse the SAME focus keyword, so Google gets one clear signal
about what the page is about.
"""

import config
from src.llm.client import LLMClient, get_client, load_prompt
from src.models.schemas import BlogMetadata, BlogRequest, KeywordPlan
from src.utils import text_tools as tt
from src.utils.logger import get_logger

logger = get_logger(__name__)

MAX_METADATA_ATTEMPTS = 2


def find_metadata_problems(meta: BlogMetadata, focus_keyword: str) -> list[str]:
    """List every metadata rule the LLM broke (empty list = all good). Plain code, no AI."""
    problems = []
    if len(meta.title) > config.TITLE_MAX_CHARS:
        problems.append(f"title is {len(meta.title)} characters, max is {config.TITLE_MAX_CHARS}")
    if len(meta.meta_description) > config.META_DESCRIPTION_MAX_CHARS:
        problems.append(f"meta_description is {len(meta.meta_description)} characters, "
                        f"max is {config.META_DESCRIPTION_MAX_CHARS}")
    for field in ("title", "meta_description", "feature_image_alt"):
        if not tt.contains_keyword(getattr(meta, field), focus_keyword):
            problems.append(f'{field} must contain "{focus_keyword}"')
    return problems


def fix_slug(slug: str, focus_keyword: str) -> str:
    """Make sure the slug is URL-safe and contains the keyword.

    This is fixed in code, not by asking the LLM again: the keyword itself,
    slugified, is always a valid and correct slug.
    """
    slug = tt.slugify(slug)
    keyword_slug = tt.slugify(focus_keyword)
    return slug if keyword_slug in slug else keyword_slug


def create_metadata(request: BlogRequest, plan: KeywordPlan, body: str,
                    llm: LLMClient | None = None,
                    initial_problems: list[str] | None = None) -> BlogMetadata:
    """Ask the LLM for metadata, check it in code, and ask once more if rules were broken.

    initial_problems: problems the validator found in earlier metadata, so the
    first attempt already knows what to avoid (used by the reviewer loop).
    """
    llm = llm or get_client()
    headings = [h.text for h in tt.extract_headings(body) if h.level == 1]
    intro = tt.first_n_words(tt.markdown_to_plain_text(body), 120)
    problems: list[str] = list(initial_problems or [])

    for attempt in range(1, MAX_METADATA_ATTEMPTS + 1):
        problem_note = ""
        if problems:
            problem_note = ("\nYour previous answer broke these rules, fix them:\n"
                            + "\n".join(f"- {p}" for p in problems))
        prompt = load_prompt(
            "metadata",
            focus_keyword=plan.focus_keyword,
            audience=request.audience,
            goal=request.goal,
            h1=headings[0] if headings else plan.topic,
            intro=intro,
            title_max=config.TITLE_MAX_CHARS,
            meta_max=config.META_DESCRIPTION_MAX_CHARS,
            keyword_slug=tt.slugify(plan.focus_keyword),
            problems=problem_note,
        )
        logger.info("Creating metadata (attempt %d)...", attempt)
        meta = llm.generate_json(prompt, BlogMetadata, system=load_prompt("system"))
        meta.slug = fix_slug(meta.slug, plan.focus_keyword)
        problems = find_metadata_problems(meta, plan.focus_keyword)
        if not problems:
            break
        logger.warning("Metadata problems: %s", "; ".join(problems))

    # If problems remain, we still return the metadata: the validator will report them.
    return meta
