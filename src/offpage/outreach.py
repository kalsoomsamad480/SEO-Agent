"""Draft personalised outreach for backlink opportunities. DRAFTS ONLY.

    guest_post / contextual          -> a pitch email to the site owner
    web2_profile                     -> a profile bio that mentions the blog
    article / image / audio          -> a short submission description

Each draft is saved as a text file in outputs/outreach/<blog-slug>/ and the
tracker row moves from "found" to "draft". Nothing is sent, posted or submitted:
you read it, change it, set it to "approved", send it yourself, then mark it "sent".
"""

import json
import re
from pathlib import Path

import config
from src.content.internal_links import page_url
from src.llm.client import LLMClient, get_client, load_prompt
from src.models.schemas import Opportunity
from src.offpage import tracker
from src.utils import text_tools as tt
from src.utils.logger import get_logger

logger = get_logger(__name__)

DRAFT_TYPES = {
    "guest_post": ("guest post pitch email",
                   "Start with 'Subject: ...' on the first line. Propose 2-3 article ideas related to "
                   "our blog's topic that would suit THEIR readers, and mention our post as a writing sample."),
    "contextual": ("polite resource-suggestion email",
                   "Start with 'Subject: ...' on the first line. Explain in one or two sentences why our "
                   "post could be a useful addition to their resource page."),
    "web2_profile": ("profile bio",
                     "Write a short first-person bio for this platform that naturally mentions our blog's topic."),
    "article_submission": ("article submission description",
                           "Write a short intro/summary to accompany a republished or adapted version of "
                           "our post (tell the human to set a canonical link to the original if the platform allows it)."),
    "image_submission": ("image submission description",
                         "Write a title, a one-paragraph description and 5 relevant tags for an image "
                         "(e.g. an infographic) based on our post."),
    "audio_submission": ("audio/podcast episode description",
                         "Write an episode title and a short description for an audio version of our post."),
}
MAX_WORDS = 180
HEADER = ("DRAFT - NOT SENT. Review, edit and personalise before sending.\n"
          "After you send it yourself, run: python main.py tracker --set {id} sent\n"
          "------------------------------------------------------------------\n\n")


def load_blog(blog_folder: Path) -> dict:
    """Read a generated blog's meta.json plus a short summary from post.md."""
    meta_file = blog_folder / "meta.json"
    if not meta_file.is_file():
        raise FileNotFoundError(f"No meta.json in {blog_folder}. Pass a folder from outputs/blogs/.")
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    post = (blog_folder / "post.md").read_text(encoding="utf-8") if (blog_folder / "post.md").is_file() else ""
    _settings, body = tt.split_front_matter(post)
    meta["summary"] = meta.get("meta_description") or tt.first_n_words(tt.markdown_to_plain_text(body), 60)
    return meta


def safe_filename(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "draft"


def draft_outreach(item: Opportunity, blog: dict, llm: LLMClient | None = None) -> str:
    """Ask the LLM for the right kind of draft for this opportunity."""
    llm = llm or get_client()
    draft_type, instructions = DRAFT_TYPES[item.category]
    prompt = load_prompt(
        "outreach", draft_type=draft_type, instructions=instructions,
        blog_title=blog["title"], blog_url=page_url(blog["slug"]), focus_keyword=blog["focus_keyword"],
        blog_summary=blog["summary"], opportunity=item.opportunity, category=item.category,
        opportunity_url=item.url, notes=item.notes or "(nothing else)", max_words=MAX_WORDS,
    )
    return llm.generate_text(prompt, system=load_prompt("system")).strip()


def create_drafts(items: list[Opportunity], blog: dict, max_drafts: int = 5,
                  llm: LLMClient | None = None) -> list[Path]:
    """Draft the top `max_drafts` "found" items, save them, and mark them "draft" in the tracker.

    We limit the number because each draft is one LLM call (free tiers have limits).
    """
    folder = config.OUTREACH_DIR / blog["slug"]
    folder.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    for item in [i for i in items if i.status == "found"][:max_drafts]:
        logger.info("Drafting %s for %s...", DRAFT_TYPES[item.category][0], item.opportunity)
        text = draft_outreach(item, blog, llm=llm)
        path = folder / f"{item.id}-{safe_filename(item.opportunity)}.txt"
        path.write_text(HEADER.format(id=item.id) + text + "\n", encoding="utf-8")
        tracker.update_item(item.id, status="draft", draft_file=str(path.relative_to(config.PROJECT_ROOT)))
        saved.append(path)
    return saved


def save_search_queries(queries: dict[str, list[str]], blog_slug: str) -> Path:
    """Save the footprint queries so you can run them yourself in any search engine."""
    folder = config.OUTREACH_DIR / blog_slug
    folder.mkdir(parents=True, exist_ok=True)
    lines = ["Search queries to find more opportunities (paste them into Google yourself).",
             "Skip any site that sells links or asks for payment: paid links break Google's rules.", ""]
    for category, category_queries in queries.items():
        lines.append(f"{category}:")
        lines += [f"  {q}" for q in category_queries]
        lines.append("")
    path = folder / "search_queries.txt"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
