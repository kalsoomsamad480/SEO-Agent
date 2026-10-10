"""Command-line entry point.

Examples:
    python main.py blog --mode manual
    python main.py blog --mode auto --niche "web development"
    python main.py blog --mode auto --niche "web development" --auto-pick
    python main.py blog --mode manual --main-page web-development-courses-for-beginners
    python main.py pages
    python main.py link-pages --main web-development-courses-for-beginners
    python main.py validate --file tests/samples/sample_blog.md
    python main.py audit --url https://example.com --max-pages 50 --explain
    python main.py outreach --blog outputs/blogs/<slug> --niche "web development"
    python main.py tracker --set <id> approved
    python main.py wordpress --check
    python main.py wordpress --blog outputs/blogs/<slug>
"""

import argparse
import sys
from pathlib import Path

import config
from src.llm.client import LLMError
from src.utils.logger import get_logger

logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Describe the commands and options the CLI understands."""
    parser = argparse.ArgumentParser(description="SEO Agent: research, write, validate and audit.")
    commands = parser.add_subparsers(dest="command", required=True)

    blog = commands.add_parser("blog", help="Create an SEO blog post")
    blog.add_argument("--mode", choices=["manual", "auto"], default="manual")
    blog.add_argument("--niche", help="Your niche, e.g. 'web development' (needed in auto mode)")
    blog.add_argument("--auto-pick", action="store_true", help="Auto mode: take the top topic")
    blog.add_argument("--audience", default="beginners", help="Auto mode: target audience")
    blog.add_argument("--goal", default="rank", help="Auto mode: educate / rank / sales / leads")
    blog.add_argument("--main-page", default="",
                      help="Slug or URL of the main (pillar) page; makes this blog a child page")

    commands.add_parser("pages", help="List main and child pages from the site map")
    link = commands.add_parser("link-pages", help="Rebuild a main page's links to its child pages")
    link.add_argument("--main", required=True, help="Slug of the main page")

    audit = commands.add_parser("audit", help="Run a technical SEO audit")
    audit.add_argument("--url", required=True)
    audit.add_argument("--max-pages", type=int, default=config.DEFAULT_MAX_PAGES)
    audit.add_argument("--no-external", action="store_true", help="Skip checking links to other sites")
    audit.add_argument("--no-speed", action="store_true", help="Skip the PageSpeed test")
    audit.add_argument("--explain", action="store_true",
                       help="Add a plain-language AI summary (uses the LLM)")

    outreach = commands.add_parser("outreach", help="Draft backlink outreach for a blog")
    outreach.add_argument("--blog", required=True, help="Folder of a generated blog")
    outreach.add_argument("--niche", default="", help="Your niche (improves relevance scoring)")
    outreach.add_argument("--max-drafts", type=int, default=5,
                          help="How many pitches to draft now (each one is an LLM call)")

    track = commands.add_parser("tracker", help="Show the backlink tracker or change a status")
    track.add_argument("--set", nargs=2, metavar=("ID", "STATUS"),
                       help="Change a status: draft, approved, sent (after YOU sent it), rejected, found")
    track.add_argument("--blog", default="", help="Only show rows for this blog slug")

    validate = commands.add_parser("validate", help="Check a Markdown blog file against the SEO rules")
    validate.add_argument("--file", required=True, help="Path to a .md file")
    validate.add_argument("--keyword", help="Focus keyword (overrides the file's settings block)")
    validate.add_argument("--audience", help="Target audience, e.g. 'beginners'")
    validate.add_argument("--check-links", action="store_true",
                          help="Also check that external links return 200 (needs internet)")

    wordpress = commands.add_parser("wordpress", help="Send a blog to WordPress as a DRAFT (never published)")
    wordpress.add_argument("--blog", help="Folder of a generated blog")
    wordpress.add_argument("--update", action="store_true",
                           help="Refresh the draft sent earlier (only while it is still a draft)")
    wordpress.add_argument("--check", action="store_true", help="Only test the WordPress login")

    return parser


# ---------------------------------------------------------------------------
# blog command
# ---------------------------------------------------------------------------
def ask(question: str) -> str:
    """Print a question and return the typed answer."""
    return input(f"{question}\n> ").strip()


def ask_manual_questions(niche: str, main_page: str):
    """Manual mode: ask the 3 questions and build a BlogRequest from the answers."""
    from src.agents import pipeline

    print("\nAnswer 3 quick questions about your blog.\n")
    topic = ask(pipeline.QUESTION_TOPIC)
    while not topic:   # the topic is the one answer we can't guess
        topic = ask("Please type a topic (Ctrl+C to quit):")
    audience = ask(pipeline.QUESTION_AUDIENCE)
    tone = ask(pipeline.QUESTION_TONE)
    goal = ask(pipeline.QUESTION_GOAL)
    if not main_page:
        main_page = ask("Optional: is this a child of a main page? Type its slug "
                        "('python main.py pages' lists them), or press Enter to skip.")
    return pipeline.build_request(topic, audience, goal, tone=tone, niche=niche,
                                  main_page=main_page)


def choose_auto_topic(args: argparse.Namespace):
    """Auto mode: find trending topics, show the top 5, and let the user pick one."""
    from src.agents import pipeline
    from src.research.trends import find_topics

    niche = args.niche or ask("What is your niche? (e.g. web development)")
    ideas = find_topics(niche, limit=5)

    print(f"\nTop topics for '{niche}':")
    for number, idea in enumerate(ideas, start=1):
        print(f"  {number}. {idea.topic}   (relevance {idea.relevance:.0%}, from {idea.source})")

    if args.auto_pick:
        chosen = ideas[0]
    else:
        answer = ask(f"Pick a topic (1-{len(ideas)}), or press Enter for 1:") or "1"
        if not answer.isdigit() or not 1 <= int(answer) <= len(ideas):
            raise ValueError(f"Please enter a number from 1 to {len(ideas)}.")
        chosen = ideas[int(answer) - 1]
    print(f"\nChosen topic: {chosen.topic}\n")
    return pipeline.build_request(chosen.topic, args.audience, args.goal, niche=niche,
                                  main_page=args.main_page)


def run_blog(args: argparse.Namespace) -> None:
    """Create one blog post: get the request (manual or auto), then run the pipeline."""
    from src.agents.pipeline import run_pipeline
    from src.llm.client import get_client
    from src.validators.seo_rules import format_report

    get_client()   # check the API key BEFORE asking questions, so you don't answer for nothing
    if args.mode == "manual":
        request = ask_manual_questions(args.niche or "", args.main_page)
    else:
        request = choose_auto_topic(args)

    result = run_pipeline(request)
    print()
    print(format_report(result.report))
    print("\nProgress: " + " -> ".join(result.history))
    print(f"Saved to: {result.folder}")
    if result.main_page_folder:
        print(f"Main page updated with a link to this post: {result.main_page_folder}")
    print("Human review required before publishing.")


# ---------------------------------------------------------------------------
# pages and link-pages commands
# ---------------------------------------------------------------------------
def run_pages() -> None:
    """Show every generated page as a tree: main pages with their children below."""
    from src.content import internal_links

    added = internal_links.sync_site_map()
    if added:
        print(f"Added {added} older blog(s) to the site map.")
    pages = internal_links.load_site_map()["pages"]
    if not pages:
        print("No pages yet. Create one with: python main.py blog")
        return
    known_urls = {entry["url"] for entry in pages.values()}
    print("Pages (slug - title):")
    for slug, entry in pages.items():
        # Top level = no parent, or a parent that isn't one of our pages.
        if entry.get("parent") in known_urls:
            continue
        print(f"  {slug} - {entry['title']}")
        if entry.get("parent"):
            print(f"      (child of external page {entry['parent']})")
        for child in internal_links.children_of(entry["url"]):
            print(f"      -> {child['url']} - {child['title']}")


def run_link_pages(args: argparse.Namespace) -> None:
    """Rebuild the Related Guides section of one main page."""
    from src.content import internal_links

    internal_links.sync_site_map()
    if not internal_links.find_page(args.main):
        raise ValueError(f"No page '{args.main}' in the site map. Run 'python main.py pages'.")
    folder = internal_links.update_main_page(args.main)
    if folder:
        print(f"Updated: {folder}")


# ---------------------------------------------------------------------------
# audit command
# ---------------------------------------------------------------------------
def run_audit_command(args: argparse.Namespace) -> None:
    """Run a technical SEO audit and save the report."""
    from src.audit.report import run_audit, save_report

    if args.max_pages < 1:
        raise ValueError("--max-pages must be at least 1.")
    report = run_audit(args.url, max_pages=args.max_pages, check_external=not args.no_external,
                       check_speed=not args.no_speed, explain=args.explain)
    folder = save_report(report)
    print()
    print(f"Audit of {report.site_url}: {report.pages_crawled} page(s) crawled")
    print(f"  High priority:   {report.count('high')}")
    print(f"  Medium priority: {report.count('medium')}")
    print(f"  Low priority:    {report.count('low')}")
    print(f"Full report: {folder / 'audit.md'}")


# ---------------------------------------------------------------------------
# outreach and tracker commands (drafts only - nothing is ever sent)
# ---------------------------------------------------------------------------
def run_outreach(args: argparse.Namespace) -> None:
    """Find backlink opportunities for one blog, track them, and draft the top pitches."""
    from src.offpage import outreach, tracker
    from src.offpage.opportunities import CATEGORIES, find_opportunities

    blog = outreach.load_blog(Path(args.blog))
    items, queries = find_opportunities(args.niche, blog["focus_keyword"], blog["slug"])
    added = tracker.add_opportunities(items)
    queries_file = outreach.save_search_queries(queries, blog["slug"])

    # Draft for this blog's rows that don't have a draft yet, best first.
    rows = sorted((i for i in tracker.load_tracker() if i.blog_slug == blog["slug"]),
                  key=lambda i: i.relevance, reverse=True)
    drafts = outreach.create_drafts(rows, blog, max_drafts=args.max_drafts) if args.max_drafts > 0 else []

    print()
    print(f"Backlink opportunities for '{blog['title']}': {len(added)} new")
    for code, label in CATEGORIES.items():
        count = sum(1 for i in rows if i.category == code)
        print(f"  {label}: {count}")
    print()
    print(f"{len(drafts)} draft(s) saved in {config.OUTREACH_DIR / blog['slug']}")
    print(f"Search queries to run yourself: {queries_file}")
    print(f"Tracker: {config.TRACKER_FILE}")
    print()
    print("Nothing has been sent. Review each draft, then:")
    print("  python main.py tracker --set <id> approved   (after reviewing)")
    print("  python main.py tracker --set <id> sent       (after YOU sent it)")


def run_tracker(args: argparse.Namespace) -> None:
    """Show the tracker, or move one item to a new status."""
    from src.offpage import tracker

    if args.set:
        item_id, status = args.set
        item = tracker.update_item(item_id, status=status.lower())
        print(f"{item.id} ({item.opportunity}) is now '{item.status}'.")
        return
    items = [i for i in tracker.load_tracker() if not args.blog or i.blog_slug == args.blog]
    print(tracker.format_table(items))


# ---------------------------------------------------------------------------
# wordpress command (drafts only - you press Publish yourself in WP Admin)
# ---------------------------------------------------------------------------
def confirm(question: str) -> bool:
    return ask(f"{question} [y/N]").lower() in ("y", "yes")


def run_wordpress(args: argparse.Namespace) -> None:
    """Test the login, or send one blog as a draft after the user confirms."""
    from src.publish import wordpress

    if args.check:
        print(f"Connected to {wordpress.get_settings()[0]} as {wordpress.check_connection()}.")
        return
    if not args.blog:
        raise ValueError("Pass --blog <folder> (or --check to test the login).")

    folder = Path(args.blog)
    post = wordpress.load_post(folder)
    site, _auth = wordpress.get_settings()
    record = wordpress.load_record(folder)
    print(f"\nBlog:      {post['title']}")
    print(f"SEO check: {post['score']} ({'passed' if post['passed'] else 'FAILED'})")
    print(f"Site:      {site}")
    if record:
        print(f"Already sent as draft {record['post_id']} on {record['sent_at']}.")
    if post["local_images"]:
        print(f"Local images to upload in WordPress yourself: {', '.join(post['local_images'])}")

    action = "Update the draft" if args.update else "Send it as a DRAFT"
    if not confirm(f"\n{action} on {site}?"):
        print("Cancelled. Nothing was sent.")
        return
    allow_failed = False
    if not post["passed"]:
        allow_failed = confirm("This blog FAILED the SEO checks. Send it anyway?")
        if not allow_failed:
            print("Cancelled. Fix it first: python main.py validate --file " + str(folder / "post.md"))
            return

    record = wordpress.send_draft(folder, update=args.update, allow_failed=allow_failed)
    print(f"\nSaved as draft {record['post_id']}. Review and publish it yourself:")
    print(f"  {record['edit_link']}")


# ---------------------------------------------------------------------------
# validate command
# ---------------------------------------------------------------------------
def run_validate(args: argparse.Namespace) -> None:
    """Validate a blog file and print the pass/fail report."""
    from src.validators.seo_rules import format_report, load_draft_from_markdown, validate_blog

    path = Path(args.file)
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")
    draft = load_draft_from_markdown(
        path.read_text(encoding="utf-8"),
        focus_keyword=args.keyword or "",
        audience=args.audience or "",
    )
    report = validate_blog(draft, check_links=args.check_links)
    print(format_report(report))


def run(args: argparse.Namespace) -> None:
    """Send the chosen command to the right part of the program."""
    if args.command == "blog":
        run_blog(args)
    elif args.command == "pages":
        run_pages()
    elif args.command == "link-pages":
        run_link_pages(args)
    elif args.command == "validate":
        run_validate(args)
    elif args.command == "audit":
        run_audit_command(args)
    elif args.command == "outreach":
        run_outreach(args)
    elif args.command == "tracker":
        run_tracker(args)
    elif args.command == "wordpress":
        run_wordpress(args)


def main() -> int:
    """Run the CLI and turn any error into a friendly message (no raw traceback)."""
    from src.publish.wordpress import WordPressError
    from src.research.trends import ResearchError

    args = build_parser().parse_args()
    try:
        run(args)
        return 0
    except config.ConfigError as error:
        logger.error("Setup problem: %s", error)
    except LLMError as error:
        logger.error("AI service problem: %s", error)
    except ResearchError as error:
        logger.error("Research problem: %s", error)
    except WordPressError as error:
        logger.error("WordPress problem: %s", error)
    except (FileNotFoundError, ValueError) as error:
        # ValueError covers bad input, e.g. a blog file without a focus keyword.
        logger.error("%s", error)
    except (KeyboardInterrupt, EOFError):
        logger.warning("Stopped by user.")
    except Exception as error:  # last safety net so the user never sees a traceback
        logger.error("Unexpected error: %s (full details in logs/app.log)", error)
        # DEBUG level = written to the log file only, not the console.
        logger.debug("Traceback:", exc_info=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
