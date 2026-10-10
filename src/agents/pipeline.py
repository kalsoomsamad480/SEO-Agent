"""The full pipeline: a BlogRequest goes in, a finished, validated, saved blog comes out.

    BlogRequest
      -> research          (KeywordPlan: keywords, real FAQ questions, verified sources)
      -> outline
      -> writer <-> reviewer loop  (write, metadata, validate, fix up to N rounds)
      -> export            (outputs/blogs/<slug>/)

Both the CLI (main.py) and the web app (app.py) call run_pipeline().
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from src.agents.research_agent import research
from src.agents.writer_reviewer_loop import run_writer_reviewer_loop
from src.content import internal_links
from src.content.outline import create_outline
from src.llm.client import LLMClient, get_client
from src.models.schemas import BlogDraft, BlogRequest, KeywordPlan, ValidationReport
from src.publish.exporter import save_blog
from src.utils.logger import get_logger
from src.validators.seo_rules import LinkChecker

logger = get_logger(__name__)

# The 3 manual-mode questions (shared by the CLI and the web app).
QUESTION_TOPIC = "1. What is the topic, product or service?"
QUESTION_AUDIENCE = "2. Who is the target audience? (e.g. beginners, business owners, students)"
QUESTION_TONE = "   What tone should we use? (press Enter for 'friendly and clear')"
QUESTION_GOAL = "3. What is the goal? 1) educate  2) rank for a keyword  3) drive sales  4) get leads"

GOALS = {"1": "educate", "2": "rank", "3": "sales", "4": "leads"}
DEFAULT_TONE = "friendly and clear"


@dataclass
class PipelineResult:
    """Everything the pipeline produced."""
    plan: KeywordPlan
    draft: BlogDraft
    report: ValidationReport
    folder: Path
    history: list[str] = field(default_factory=list)
    main_page_folder: Path | None = None   # set when a main page was updated with a new link


def parse_goal(answer: str) -> str:
    """Accept "1"-"4" or a word like "sales" / "drive sales" / "leads"; default "educate"."""
    answer = answer.strip().lower()
    if answer in GOALS:
        return GOALS[answer]
    for goal in GOALS.values():
        if goal in answer:
            return goal
    if "keyword" in answer:
        return "rank"
    return "educate"


def build_request(topic: str, audience: str, goal: str, tone: str = "", niche: str = "",
                  main_page: str = "") -> BlogRequest:
    """Turn the answers to the 3 questions into a BlogRequest (with friendly defaults).

    main_page: optional slug or URL of the main page, which makes this blog a child page.
    """
    if not topic.strip():
        raise ValueError("The topic can't be empty. Please describe what the blog is about.")
    main_page_url, main_page_title = resolve_main_page(main_page)
    return BlogRequest(
        topic=topic.strip(),
        audience=audience.strip() or "beginners",
        tone=tone.strip() or DEFAULT_TONE,
        goal=parse_goal(goal),
        niche=niche.strip(),
        main_page_url=main_page_url or None,
        main_page_title=main_page_title,
    )


def run_pipeline(request: BlogRequest, llm: LLMClient | None = None,
                 link_checker: LinkChecker | None = None,
                 on_progress: Callable[[str], None] | None = None) -> PipelineResult:
    """Run every step for one blog and save the result.

    on_progress: optional function called with a short message before each step
    (the web app uses it to update its progress bar).
    """
    llm = llm or get_client()

    def progress(message: str) -> None:
        logger.info("== %s", message)
        if on_progress:
            on_progress(message)

    progress("Step 1/4: Researching keywords, questions and sources")
    plan = research(request, llm=llm)

    progress("Step 2/4: Creating the outline")
    outline = create_outline(request, plan, llm=llm)

    progress("Step 3/4: Writing and checking the blog")
    result = run_writer_reviewer_loop(request, plan, outline, llm=llm, link_checker=link_checker)

    progress("Step 4/4: Saving the files")
    folder = save_blog(result.draft, result.report)
    internal_links.register_page(result.draft, parent_url=request.main_page_url)
    main_page_folder = None
    if request.main_page_url:
        # A new child page: refresh its main page's "Related Guides" list.
        found = internal_links.find_page(request.main_page_url)
        if found:
            main_page_folder = internal_links.update_main_page(found[0])
    return PipelineResult(plan, result.draft, result.report, folder, result.history,
                          main_page_folder)


def resolve_main_page(slug_or_url: str) -> tuple[str, str]:
    """Turn what the user typed (a slug or URL) into (main page URL, main page title).

    Pages from our site map give us both. Any other http(s) URL is allowed too
    (e.g. a main page you wrote by hand), but then we don't know its title.
    """
    slug_or_url = slug_or_url.strip()
    if not slug_or_url:
        return "", ""
    found = internal_links.find_page(slug_or_url)
    if found:
        return found[1]["url"], found[1]["title"]
    if slug_or_url.startswith(("http://", "https://", "/")):
        return slug_or_url, ""
    raise ValueError(f"No main page '{slug_or_url}' in the site map. "
                     "Run 'python main.py pages' to see the available slugs.")
