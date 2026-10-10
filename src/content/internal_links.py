"""Main (pillar) page <-> child page linking, and the site map that remembers it.

A MAIN page covers a broad topic ("Web development for beginners").
CHILD pages cover one sub-topic each ("Best HTML courses", "CSS basics").
    - every child links UP to its main page
    - the main page links DOWN to every child, in a "Related Guides" section

outputs/site_map.json remembers every page we generated:
    {
      "pages": {
        "web-development-guide": {"title": "...", "url": "/web-development-guide/",
                                  "focus_keyword": "...", "parent": null},
        "best-html-courses":     {"title": "...", "url": "/best-html-courses/",
                                  "focus_keyword": "...", "parent": "/web-development-guide/"}
      }
    }
"""

import json
import re
from pathlib import Path

import config
from src.models.schemas import BlogDraft
from src.utils import text_tools as tt
from src.utils.logger import get_logger

logger = get_logger(__name__)

# HTML comments mark the section we manage, so we can find and replace it later.
# Readers never see them (browsers hide comments).
RELATED_START = "<!-- related-guides:start -->"
RELATED_END = "<!-- related-guides:end -->"
RELATED_HEADING = "## Related Guides"
FAQ_HEADING = re.compile(r"^##\s+.*(faq|frequently asked questions)", re.IGNORECASE | re.MULTILINE)


# ---------------------------------------------------------------------------
# URLs and the site map file
# ---------------------------------------------------------------------------
def page_url(slug: str) -> str:
    """The public URL of a page: SITE_URL + /slug/ (or just /slug/ if SITE_URL is empty)."""
    return f"{config.SITE_URL}/{slug}/"


def load_site_map() -> dict:
    """Read outputs/site_map.json (an empty map if it doesn't exist yet)."""
    path: Path = config.SITE_MAP_FILE
    if not path.is_file():
        return {"pages": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        # Don't crash on a hand-edited file with a typo; tell the user instead.
        raise ValueError(f"{path} is not valid JSON. Fix or delete it, then try again.") from None


def save_site_map(site_map: dict) -> None:
    """Write the site map back to disk."""
    config.SITE_MAP_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.SITE_MAP_FILE.write_text(json.dumps(site_map, indent=2), encoding="utf-8")


def register_page(draft: BlogDraft, parent_url: str | None = None) -> None:
    """Add (or update) a page in the site map. parent_url makes it a child page."""
    site_map = load_site_map()
    site_map["pages"][draft.slug] = {
        "title": draft.title,
        "url": page_url(draft.slug),
        "focus_keyword": draft.focus_keyword,
        "parent": parent_url or None,
    }
    save_site_map(site_map)
    logger.info("Site map: saved '%s'%s.", draft.slug, f" (child of {parent_url})" if parent_url else "")


def find_page(slug_or_url: str) -> tuple[str, dict] | None:
    """Look up a page by slug or URL. Returns (slug, entry) or None."""
    wanted = slug_or_url.strip().rstrip("/")
    for slug, entry in load_site_map()["pages"].items():
        if wanted in (slug, entry["url"].rstrip("/")):
            return slug, entry
    return None


def children_of(main_url: str) -> list[dict]:
    """All pages whose parent is main_url, sorted by title."""
    pages = load_site_map()["pages"].values()
    children = [p for p in pages if (p.get("parent") or "").rstrip("/") == main_url.rstrip("/")]
    return sorted(children, key=lambda page: page["title"].lower())


def sync_site_map() -> int:
    """Add blogs that exist in outputs/blogs/ but are missing from the site map.

    Useful for blogs made before Phase 5. Returns how many were added.
    """
    site_map = load_site_map()
    added = 0
    for meta_file in sorted(config.BLOGS_DIR.glob("*/meta.json")):
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        if meta["slug"] not in site_map["pages"]:
            site_map["pages"][meta["slug"]] = {
                "title": meta["title"], "url": page_url(meta["slug"]),
                "focus_keyword": meta["focus_keyword"], "parent": meta.get("main_page_url"),
            }
            added += 1
    save_site_map(site_map)
    return added


# ---------------------------------------------------------------------------
# Editing the Markdown
# ---------------------------------------------------------------------------
def insert_before_faq(body: str, block: str) -> str:
    """Insert a block of Markdown just before the FAQ section (which must stay last)."""
    match = FAQ_HEADING.search(body)
    if not match:
        return body.rstrip() + "\n\n" + block + "\n"
    return body[:match.start()] + block + "\n\n" + body[match.start():]


def add_main_page_link(body: str, main_url: str, main_title: str = "") -> str:
    """Make sure a child page links to its main page (adds one sentence if the link is missing)."""
    already_linked = any(link.url.rstrip("/") == main_url.rstrip("/")
                         for link in tt.extract_links(body))
    if already_linked:
        return body
    # Descriptive anchor text: the main page's title, never "click here".
    anchor = main_title or "complete beginner's guide on this topic"
    sentence = f"Want the bigger picture? Read our [{anchor}]({main_url})."
    return insert_before_faq(body, sentence)


def build_related_section(children: list[dict]) -> str:
    """The Markdown block listing every child page, wrapped in our markers."""
    lines = [RELATED_START, RELATED_HEADING, "",
             "Go deeper with these guides on specific topics:", ""]
    lines += [f"- [{child['title']}]({child['url']})" for child in children]
    lines.append(RELATED_END)
    return "\n".join(lines)


def set_related_guides(body: str, children: list[dict]) -> str:
    """Replace (or add) the Related Guides section on a main page."""
    # Remove the old section first, so running this twice doesn't duplicate it.
    pattern = re.compile(re.escape(RELATED_START) + r".*?" + re.escape(RELATED_END) + r"\n*", re.DOTALL)
    body = pattern.sub("", body)
    if not children:
        return body
    return insert_before_faq(body, build_related_section(children))


def update_main_page(main_slug: str) -> Path | None:
    """Rebuild a main page's Related Guides section from the site map, re-check it and save it.

    Returns the folder it was saved in, or None if the main page wasn't generated by us.
    """
    # Imported here to avoid a circular import (the exporter is used by many modules).
    from src.publish.exporter import save_blog
    from src.validators.seo_rules import load_draft_from_markdown, validate_blog

    post_file = config.BLOGS_DIR / main_slug / "post.md"
    if not post_file.is_file():
        logger.info("Main page '%s' isn't in outputs/blogs, so it can't be updated here. "
                    "Add links to its children by hand.", main_slug)
        return None

    draft = load_draft_from_markdown(post_file.read_text(encoding="utf-8"))
    children = children_of(page_url(main_slug))
    draft.body_markdown = set_related_guides(draft.body_markdown, children)
    draft.child_page_urls = [child["url"] for child in children]
    report = validate_blog(draft)
    folder = save_blog(draft, report)
    logger.info("Main page '%s' now links to %d child page(s). %s",
                main_slug, len(children), report.score)
    return folder
