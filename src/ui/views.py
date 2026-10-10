"""The pages of the web app. app.py puts them in the sidebar menu.

Each page is one function. They only handle the screen: the real work is
done by the same functions the command line uses (pipeline, audit, outreach).
"""

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

import config
from src.agents import pipeline
from src.content import internal_links
from src.llm.client import LLMClient, LLMError
from src.models.schemas import AuditReport
from src.publish import wordpress
from src.research.trends import ResearchError
from src.ui.components import (badge, card, chips, empty_state, esc, notice, page_header, section,
                               status_table, steps)
from src.utils import text_tools as tt
from src.utils.logger import get_logger

logger = get_logger("app")

GOAL_LABELS = {"educate": "Educate readers", "rank": "Rank for a keyword",
               "sales": "Drive sales", "leads": "Get leads"}
NO_MAIN_PAGE = "None (standalone or main page)"
REVIEW_TEXT = ("<b>Human review required before publishing.</b> This tool never publishes or sends "
               "anything by itself. Check facts, links and tone before you use any output.")


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------
def friendly_error(error: Exception) -> None:
    """Show a clear message instead of a raw traceback (details go to logs/app.log)."""
    if isinstance(error, config.ConfigError):
        st.error(f"Setup problem: {error}", icon=":material/key:")
    elif isinstance(error, LLMError):
        st.error(f"AI service problem: {error}", icon=":material/cloud_off:")
    elif isinstance(error, ResearchError):
        st.error(f"Research problem: {error}", icon=":material/search_off:")
    elif isinstance(error, (ValueError, FileNotFoundError)):
        st.error(str(error), icon=":material/error:")
    else:
        st.error(f"Unexpected error: {error}. Full details are in logs/app.log.", icon=":material/error:")
    logger.debug("Error in the web app", exc_info=error)


def load_blogs() -> list[dict]:
    """Every saved blog with its metadata and report, newest first."""
    blogs = []
    for meta_file in config.BLOGS_DIR.glob("*/meta.json"):
        folder = meta_file.parent
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            report_file = folder / "validation_report.json"
            report = json.loads(report_file.read_text(encoding="utf-8")) if report_file.is_file() else {}
        except (OSError, ValueError):
            continue   # skip a half-written or hand-edited folder instead of crashing
        blogs.append({"folder": folder, "meta": meta, "report": report,
                      "modified": datetime.fromtimestamp(folder.stat().st_mtime)})
    return sorted(blogs, key=lambda b: b["modified"], reverse=True)


def load_audits() -> list[Path]:
    """Saved audit folders, newest first."""
    files = sorted(config.AUDITS_DIR.glob("*/audit.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [f.parent for f in files]


def load_tracker_safely() -> list:
    from src.offpage import tracker
    try:
        return tracker.load_tracker()
    except ValueError as error:
        st.error(str(error))
        return []


def score_badge(report: dict) -> str:
    if not report:
        return badge("No report", "neutral")
    return badge(report.get("score", ""), "success" if report.get("passed") else "warning")


def page_link(name: str, label: str, icon: str) -> None:
    """A link to another page of the app (pages are registered by app.py)."""
    pages = st.session_state.get("pages", {})
    if name in pages:
        st.page_link(pages[name], label=label, icon=icon)


def mask(secret: str) -> str:
    return "••••" + secret[-4:] if secret else "Not set"


def download_buttons(folder: Path, files: list[tuple[str, str, str]]) -> None:
    columns = st.columns(len(files))
    for column, (name, label, mime) in zip(columns, files):
        path = folder / name
        with column:
            if path.is_file():
                st.download_button(label, path.read_bytes(), file_name=path.name, mime=mime,
                                   key=f"dl-{path}", icon=":material/download:", width="stretch")


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
def dashboard_view() -> None:
    page_header("Overview", "Dashboard", "Your content, audits and outreach at a glance.")
    notice(REVIEW_TEXT)

    blogs = load_blogs()
    audits = load_audits()
    items = load_tracker_safely()
    passing = sum(1 for b in blogs if b["report"].get("passed"))
    awaiting = sum(1 for i in items if i.status == "draft")

    kpis = st.columns(4)
    kpis[0].metric("Blog posts", len(blogs))
    kpis[1].metric("Passing all SEO rules", f"{passing}/{len(blogs)}" if blogs else "0")
    kpis[2].metric("Site audits", len(audits))
    kpis[3].metric("Drafts to review", awaiting)

    left, right = st.columns([3, 2], gap="medium")
    with left:
        with card("recent-blogs"):
            section("Recent blog posts", "The latest posts and their SEO check result.")
            if not blogs:
                empty_state("No posts yet", "Create your first SEO blog post to see it here.")
            for blog in blogs[:6]:
                meta = blog["meta"]
                st.markdown(
                    f'<div class="sa-row"><div><div class="sa-row-title">{esc(meta["title"])}</div>'
                    f'<div class="sa-row-meta">{esc(meta["focus_keyword"])} · '
                    f'{blog["modified"]:%d %b %Y}</div></div>{score_badge(blog["report"])}</div>',
                    unsafe_allow_html=True)
            page_link("library", "Open blog library", ":material/arrow_forward:")

        if audits:
            report = AuditReport.model_validate_json((audits[0] / "audit.json").read_text(encoding="utf-8"))
            with card("latest-audit"):
                section("Latest site audit", f"{report.site_url} · {report.created_at:%d %b %Y, %H:%M}")
                cols = st.columns(4)
                cols[0].metric("Pages", report.pages_crawled)
                cols[1].metric("High", report.count("high"))
                cols[2].metric("Medium", report.count("medium"))
                cols[3].metric("Low", report.count("low"))
                page_link("audit", "View audit details", ":material/arrow_forward:")

    with right:
        with card("quick-actions"):
            section("Quick actions")
            page_link("create", "Create a blog post", ":material/edit_note:")
            page_link("audit", "Audit a website", ":material/travel_explore:")
            page_link("backlinks", "Find backlink opportunities", ":material/link:")

        with card("setup"):
            section("Setup checklist", "Optional keys unlock more features.")
            checks = [
                ("AI key (required)", bool(config.LLM_API_KEY)),
                ("Website address (SITE_URL)", bool(config.SITE_URL)),
                ("PageSpeed key (page speed)", bool(config.PAGESPEED_API_KEY)),
                ("Brave Search key (guest posts)", bool(config.BRAVE_SEARCH_API_KEY)),
            ]
            rows = "".join(
                f'<div class="sa-row"><div class="sa-row-title" style="font-weight:500">{esc(label)}</div>'
                f'{badge("Ready", "success") if ok else badge("Not set", "neutral")}</div>'
                for label, ok in checks)
            st.markdown(rows, unsafe_allow_html=True)
            page_link("settings", "Open settings", ":material/settings:")


# ---------------------------------------------------------------------------
# Create Blog
# ---------------------------------------------------------------------------
def main_page_choice(key: str) -> str:
    """Dropdown of existing pages, so a new blog can become a child page."""
    internal_links.sync_site_map()
    pages = internal_links.load_site_map()["pages"]
    options = [NO_MAIN_PAGE] + list(pages)
    choice = st.selectbox("Main (pillar) page", options, key=key,
                          help="Pick a main page to make this post a child page. They will link to each other.",
                          format_func=lambda s: s if s == NO_MAIN_PAGE else pages[s]["title"])
    return "" if choice == NO_MAIN_PAGE else choice


def run_blog_pipeline(request) -> None:
    """Run the full pipeline with live progress, then open the result in the library."""
    with st.status("Creating your blog post. This takes 3-10 minutes on a free AI plan.",
                   expanded=True) as status:
        try:
            result = pipeline.run_pipeline(request, on_progress=st.write)
        except Exception as error:   # shown nicely; the app keeps running
            status.update(label="Something went wrong", state="error")
            friendly_error(error)
            return
        status.update(label=f"Finished: {result.report.score}", state="complete", expanded=False)
    st.session_state["selected_blog"] = str(result.folder)
    if result.main_page_folder:
        st.info("The main page was updated with a link to this post.", icon=":material/link:")
    show_blog(result.folder)


def manual_form() -> None:
    with st.form("manual", border=False):
        section("Tell us about the post", "Three quick questions decide the purpose of the blog.")
        left, right = st.columns(2, gap="medium")
        with left:
            topic = st.text_input("1 · Topic, product or service", placeholder="e.g. Best free HTML courses")
            audience = st.text_input("2 · Target audience", value="beginners",
                                     help="e.g. beginners, business owners, students")
            tone = st.text_input("Tone", value=pipeline.DEFAULT_TONE)
        with right:
            goal = st.selectbox("3 · Goal of the post", list(GOAL_LABELS), format_func=GOAL_LABELS.get)
            niche = st.text_input("Niche (optional)", placeholder="e.g. web development")
            main_page = main_page_choice("manual-main")
        submitted = st.form_submit_button("Write the blog post", type="primary", icon=":material/auto_awesome:")
    if submitted:
        try:
            request = pipeline.build_request(topic, audience, goal, tone=tone, niche=niche, main_page=main_page)
        except ValueError as error:
            st.error(str(error), icon=":material/error:")
            return
        run_blog_pipeline(request)


def auto_form() -> None:
    from src.research.trends import find_topics

    section("Find trending topics", "We check Google Trends (with Google autocomplete as a backup).")
    col_input, col_button = st.columns([4, 1], vertical_alignment="bottom")
    with col_input:
        niche = st.text_input("Your niche", placeholder="e.g. web development")
    with col_button:
        search = st.button("Find topics", disabled=not niche.strip(), width="stretch", icon=":material/search:")
    if search:
        with st.spinner("Searching..."):
            try:
                st.session_state["topics"] = find_topics(niche.strip(), limit=5)
                st.session_state["topics_niche"] = niche.strip()
            except Exception as error:
                friendly_error(error)

    topics = st.session_state.get("topics")
    if not topics:
        return
    choice = st.radio("Top topics", range(len(topics)),
                      format_func=lambda i: f"{topics[i].topic}  —  {topics[i].relevance:.0%} relevant")
    left, right = st.columns(2, gap="medium")
    with left:
        audience = st.text_input("Target audience", value="beginners", key="auto-audience")
        goal = st.selectbox("Goal", list(GOAL_LABELS), index=1, format_func=GOAL_LABELS.get, key="auto-goal")
    with right:
        main_page = main_page_choice("auto-main")
    if st.button("Write a post on this topic", type="primary", icon=":material/auto_awesome:"):
        try:
            request = pipeline.build_request(topics[choice].topic, audience, goal,
                                             niche=st.session_state["topics_niche"], main_page=main_page)
        except ValueError as error:
            st.error(str(error), icon=":material/error:")
            return
        run_blog_pipeline(request)


def create_blog_view() -> None:
    page_header("Content", "Create Blog Post",
                "Research, write and SEO-check a new post. Every post is validated against 22 rules.")
    main, side = st.columns([2, 1], gap="large")
    with main:
        with card("create-form"):
            mode = st.segmented_control("Topic source", ["Manual", "Auto (trending)"], default="Manual",
                                        key="create-mode")
            st.write("")
            if mode == "Auto (trending)":
                auto_form()
            else:
                manual_form()
    with side:
        with card("how-it-works"):
            section("What happens next")
            steps([
                ("Research", "Focus keyword, real questions people ask, verified sources."),
                ("Outline", "H1, sections and FAQ planned around the keyword."),
                ("Write & review", "AI writes; code checks 22 SEO rules and asks for fixes (max 3 rounds)."),
                ("Save", "Markdown, HTML, metadata and the SEO report."),
            ])
        notice("Writing takes a few minutes on free AI plans. Keep this tab open.", tone="info")


# ---------------------------------------------------------------------------
# Blog Library
# ---------------------------------------------------------------------------
def show_blog(folder: Path) -> None:
    """One saved blog: summary card, SEO checks, preview and downloads."""
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    report_file = folder / "validation_report.json"
    report = json.loads(report_file.read_text(encoding="utf-8")) if report_file.is_file() else {}

    with card(f"blog-{meta['slug']}"):
        title_col, score_col = st.columns([4, 1], vertical_alignment="center")
        with title_col:
            st.markdown(f'<p class="sa-section" style="font-size:1.2rem">{esc(meta["title"])}</p>'
                        f'<p class="sa-caption">/{esc(meta["slug"])}/</p>', unsafe_allow_html=True)
        with score_col:
            st.markdown(f'<div style="text-align:right">{score_badge(report)}</div>', unsafe_allow_html=True)
        st.markdown(chips([meta["focus_keyword"], *meta.get("secondary_keywords", [])]), unsafe_allow_html=True)
        if meta.get("meta_description"):
            st.caption(meta["meta_description"])

        checks_tab, preview_tab, files_tab, wp_tab = st.tabs(["SEO checks", "Preview", "Files", "WordPress"])
        with checks_tab:
            if report:
                rows = [{"Status": "SKIP" if r["skipped"] else ("PASS" if r["passed"] else "FAIL"),
                         "Rule": r["name"], "Result": r["reason"], "How to fix": r["fix_hint"]}
                        for r in report["results"]]
                df = pd.DataFrame(rows)
                st.dataframe(status_table(df, ["Status"]), hide_index=True, width="stretch",
                             column_config={"Status": st.column_config.TextColumn(width="small")})
            else:
                st.info("No SEO report saved for this post.")
        with preview_tab:
            post = folder / "post.md"
            if post.is_file():
                _settings, body = tt.split_front_matter(post.read_text(encoding="utf-8"))
                st.markdown(body)
        with files_tab:
            st.caption(f"Saved in `{folder}`")
            download_buttons(folder, [("post.md", "Markdown", "text/markdown"),
                                      ("post.html", "HTML page", "text/html"),
                                      ("meta.json", "Metadata", "application/json"),
                                      ("validation_report.json", "SEO report", "application/json")])
        with wp_tab:
            wordpress_panel(folder)


def wordpress_panel(folder: Path) -> None:
    """Send one blog to WordPress as a draft, only after the user ticks the confirmation."""
    st.caption("Sends the post as a **draft**. You review it in WP Admin and press Publish yourself.")
    if not wordpress.is_configured():
        st.info("WordPress is not set up. Add WORDPRESS_URL, WORDPRESS_USERNAME and "
                "WORDPRESS_APP_PASSWORD (an Application Password) to .env, then restart the app.",
                icon=":material/key:")
        return
    try:
        post = wordpress.load_post(folder)
        record = wordpress.load_record(folder)
    except Exception as error:
        friendly_error(error)
        return

    if record:
        st.success(f"Sent as draft {record['post_id']} on {record['sent_at']}. "
                   f"[Open it in WordPress]({record['edit_link']})", icon=":material/check_circle:")
    if post["local_images"]:
        st.warning("Upload these images in WordPress and swap the links: "
                   + ", ".join(f"`{src}`" for src in post["local_images"]), icon=":material/image:")
    if not post["passed"]:
        st.warning(f"This post did not pass the SEO checks ({post['score']}).", icon=":material/warning:")

    key = folder.name
    reviewed = st.checkbox("I reviewed this post and want to send it to WordPress as a draft",
                           key=f"wp-ok-{key}")
    allow_failed = post["passed"] or st.checkbox("Send it even though it failed the SEO checks",
                                                 key=f"wp-failed-{key}")
    label = "Update draft" if record else "Send as draft"
    if st.button(label, type="primary", icon=":material/upload:", key=f"wp-send-{key}",
                 disabled=not (reviewed and allow_failed)):
        with st.spinner("Sending to WordPress..."):
            try:
                record = wordpress.send_draft(folder, update=bool(record), allow_failed=not post["passed"])
                st.success(f"Saved as draft {record['post_id']}. "
                           f"[Review and publish it in WordPress]({record['edit_link']})",
                           icon=":material/check_circle:")
            except wordpress.WordPressError as error:
                st.error(f"WordPress problem: {error}", icon=":material/cloud_off:")
            except Exception as error:
                friendly_error(error)


def library_view() -> None:
    page_header("Content", "Blog Library", "Every post you've generated, with its SEO checks and files.")
    blogs = load_blogs()
    if not blogs:
        with card("library-empty"):
            empty_state("No posts yet", "Create your first post and it will appear here.")
            page_link("create", "Create a blog post", ":material/edit_note:")
        return

    folders = [str(b["folder"]) for b in blogs]
    titles = {str(b["folder"]): b["meta"]["title"] for b in blogs}
    selected = st.session_state.get("selected_blog")
    index = folders.index(selected) if selected in folders else 0
    choice = st.selectbox("Post", folders, index=index, format_func=titles.get)
    st.session_state["selected_blog"] = choice

    with st.expander(f"All posts ({len(blogs)})"):
        overview = pd.DataFrame([{"Title": b["meta"]["title"], "Focus keyword": b["meta"]["focus_keyword"],
                                  "SEO score": b["report"].get("score", "-"),
                                  "Updated": f'{b["modified"]:%Y-%m-%d %H:%M}'} for b in blogs])
        st.dataframe(overview, hide_index=True, width="stretch")
    show_blog(Path(choice))


# ---------------------------------------------------------------------------
# Site Audit
# ---------------------------------------------------------------------------
def show_audit(report: AuditReport, folder: Path) -> None:
    kpis = st.columns(4)
    kpis[0].metric("Pages crawled", report.pages_crawled)
    kpis[1].metric("High priority", report.count("high"))
    kpis[2].metric("Medium priority", report.count("medium"))
    kpis[3].metric("Low priority", report.count("low"))

    if report.explanation:
        with card("audit-summary"):
            section("Summary", "Written by the AI, based only on the findings below.")
            st.markdown(report.explanation)

    speed_rows, speed_notes = [], []
    for device in ("mobile", "desktop"):
        data = report.page_speed.get(device)
        if data and "error" not in data:
            speed_rows.append({"Device": device.capitalize(), "Score": f"{data['performance_score']}/100",
                               "LCP": f"{data['lcp']['seconds']} s", "LCP rating": data["lcp"]["rating"],
                               "FCP": f"{data['fcp']['seconds']} s", "FCP rating": data["fcp"]["rating"]})
        elif data:
            speed_notes.append(f"{device.capitalize()}: {data['error']}")
    if speed_rows or speed_notes:
        with card("audit-speed"):
            section("Page speed", "Good: LCP up to 2.5 s, FCP up to 1.8 s.")
            if speed_rows:
                st.dataframe(pd.DataFrame(speed_rows), hide_index=True, width="stretch")
            for note in speed_notes:
                st.caption(f"Skipped. {note}")

    with card("audit-issues"):
        top, filter_col = st.columns([2, 2], vertical_alignment="bottom")
        with top:
            section("Issues", "Sorted by priority, each with a suggested fix.")
        with filter_col:
            severities = st.multiselect("Priority", ["high", "medium", "low"], default=["high", "medium", "low"],
                                        label_visibility="collapsed")
        rows = [{"Priority": i.severity, "Issue": i.issue_type.replace("_", " ").capitalize(),
                 "Page": i.page_url, "Details": i.detail, "How to fix": i.suggested_fix}
                for i in report.issues if i.severity in severities]
        if rows:
            st.dataframe(status_table(pd.DataFrame(rows), ["Priority"]), hide_index=True, width="stretch",
                         column_config={"Page": st.column_config.LinkColumn("Page")})
        else:
            empty_state("Nothing to show", "No issues match this filter.")
        download_buttons(folder, [("audit.md", "Report (Markdown)", "text/markdown"),
                                  ("audit.json", "Report (JSON)", "application/json")])


def audit_view() -> None:
    from src.audit.report import run_audit, save_report

    page_header("Technical SEO", "Site Audit",
                "Crawl a website politely and find duplicate content, broken links, missing tags and slow pages.")
    with card("audit-form"):
        with st.form("audit", border=False):
            url_col, pages_col = st.columns([3, 1], gap="medium")
            with url_col:
                url = st.text_input("Website address", placeholder="https://example.com")
            with pages_col:
                max_pages = st.number_input("Max pages", 1, 500, config.DEFAULT_MAX_PAGES)
            opt1, opt2, opt3 = st.columns(3)
            check_external = opt1.toggle("Check external links", value=True)
            check_speed = opt2.toggle("Test page speed", value=bool(config.PAGESPEED_API_KEY),
                                      help="Works best with a free PAGESPEED_API_KEY in .env.")
            explain = opt3.toggle("AI summary", value=False)
            submitted = st.form_submit_button("Run audit", type="primary", icon=":material/play_arrow:")
        st.caption("Obeys robots.txt, stays on this site and pauses between requests. "
                   "Only audit sites you own or have permission to test.")

    if submitted:
        if not url.strip():
            st.error("Please enter a website address.", icon=":material/error:")
        else:
            with st.status("Auditing the site. A few minutes for 50 pages.", expanded=False) as status:
                try:
                    report = run_audit(url.strip(), max_pages=int(max_pages), check_external=check_external,
                                       check_speed=check_speed, explain=explain)
                    st.session_state["selected_audit"] = str(save_report(report))
                    status.update(label="Audit finished", state="complete")
                except Exception as error:
                    status.update(label="Audit failed", state="error")
                    friendly_error(error)

    audits = load_audits()
    if not audits:
        return
    names = [str(a) for a in audits]
    selected = st.session_state.get("selected_audit")
    choice = st.selectbox("Report", names, index=names.index(selected) if selected in names else 0,
                          format_func=lambda p: Path(p).name)
    report = AuditReport.model_validate_json((Path(choice) / "audit.json").read_text(encoding="utf-8"))
    show_audit(report, Path(choice))


# ---------------------------------------------------------------------------
# Backlinks
# ---------------------------------------------------------------------------
def save_status_changes(original: list, edited: pd.DataFrame) -> None:
    """Apply status changes from the table, one by one, using the tracker's safety rules."""
    from src.offpage import tracker

    changed = 0
    for item, new_status in zip(original, edited["status"]):
        if new_status != item.status:
            try:
                tracker.update_item(item.id, status=new_status)
                changed += 1
            except ValueError as error:
                st.error(str(error), icon=":material/block:")
    if changed:
        st.toast(f"Saved {changed} status change(s).", icon=":material/check_circle:")


def find_opportunities_card() -> None:
    from src.offpage import outreach, tracker
    from src.offpage.opportunities import find_opportunities

    blogs = load_blogs()
    with card("find-opps"):
        section("Find opportunities", "For one of your posts: platforms, guest-post sites and drafted pitches.")
        if not blogs:
            empty_state("No posts yet", "Create a blog post first.")
            return
        col1, col2, col3 = st.columns([2, 2, 1], vertical_alignment="bottom")
        with col1:
            folder = st.selectbox("Blog post", [b["folder"] for b in blogs],
                                  format_func=lambda p: json.loads((p / "meta.json").read_text(encoding="utf-8"))["title"])
        with col2:
            niche = st.text_input("Niche", placeholder="e.g. web development")
        with col3:
            max_drafts = st.number_input("Drafts", 0, 20, 3, help="Each draft is one AI call.")
        if st.button("Find and draft", type="primary", icon=":material/travel_explore:"):
            with st.status("Finding opportunities and drafting...", expanded=False) as status:
                try:
                    blog = outreach.load_blog(folder)
                    items, queries = find_opportunities(niche, blog["focus_keyword"], blog["slug"])
                    tracker.add_opportunities(items)
                    outreach.save_search_queries(queries, blog["slug"])
                    rows = sorted((i for i in tracker.load_tracker() if i.blog_slug == blog["slug"]),
                                  key=lambda i: i.relevance, reverse=True)
                    drafts = outreach.create_drafts(rows, blog, max_drafts=int(max_drafts))
                    status.update(label=f"{len(drafts)} draft(s) written", state="complete")
                except Exception as error:
                    status.update(label="Something went wrong", state="error")
                    friendly_error(error)
        if not config.BRAVE_SEARCH_API_KEY:
            st.caption("Add BRAVE_SEARCH_API_KEY to .env to also find guest-post and resource pages.")


def backlinks_view() -> None:
    from src.offpage.opportunities import CATEGORIES

    page_header("Off-page SEO", "Backlinks",
                "Find relevant opportunities and draft outreach. You review, approve and send everything yourself.")
    notice("<b>Drafts only.</b> This assistant never creates accounts, submits, posts or sends anything. "
           "Status flow: found → draft → approved → sent (after <i>you</i> send it).", tone="info")
    find_opportunities_card()

    items = load_tracker_safely()
    if not items:
        return
    counts = st.columns(5)
    for column, status in zip(counts, ["found", "draft", "approved", "sent", "rejected"]):
        column.metric(status.capitalize(), sum(1 for i in items if i.status == status))

    with card("tracker"):
        head, filter_col = st.columns([2, 2], vertical_alignment="bottom")
        with head:
            section("Tracker", "Change a status in the table, then save.")
        with filter_col:
            blogs = sorted({i.blog_slug for i in items})
            selected = st.selectbox("Blog", ["All posts"] + blogs, label_visibility="collapsed")
        items = [i for i in items if selected == "All posts" or i.blog_slug == selected]
        table = pd.DataFrame([{"status": i.status, "opportunity": i.opportunity,
                               "category": CATEGORIES[i.category], "relevance": i.relevance,
                               "url": i.url, "updated": i.date, "id": i.id} for i in items])
        edited = st.data_editor(
            table, hide_index=True, width="stretch", key="tracker-editor",
            disabled=[c for c in table.columns if c != "status"],
            column_config={
                "status": st.column_config.SelectboxColumn(
                    "Status", options=["found", "draft", "approved", "sent", "rejected"], required=True),
                "opportunity": "Opportunity", "category": "Category", "updated": "Updated",
                "id": st.column_config.TextColumn("ID", width="small"),
                "url": st.column_config.LinkColumn("URL"),
                "relevance": st.column_config.ProgressColumn("Relevance", min_value=0.0, max_value=1.0,
                                                             format="percent"),
            },
        )
        if st.button("Save status changes", icon=":material/save:"):
            save_status_changes(items, edited)
            st.rerun()

    drafted = [i for i in items if i.draft_file]
    if drafted:
        with card("drafts"):
            section("Drafts", "Read, edit and personalise before sending.")
            for item in drafted:
                path = config.PROJECT_ROOT / item.draft_file
                with st.expander(f"{item.opportunity}  ·  {item.status}"):
                    if path.is_file():
                        st.code(path.read_text(encoding="utf-8"), language=None, wrap_lines=True)
                    else:
                        st.warning(f"Draft file not found: {path}")


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
def settings_view() -> None:
    page_header("System", "Settings",
                "Settings come from the .env file. Edit it, save, then restart the app to apply changes.")
    if not (config.PROJECT_ROOT / ".env").is_file():
        st.error("No .env file found. Copy .env.example to .env and add your keys.", icon=":material/key_off:")

    left, right = st.columns(2, gap="medium")
    with left:
        with card("ai-settings"):
            section("AI provider", "Any OpenAI-compatible API. Free tiers: Gemini, Groq, OpenRouter.")
            rows = [("Model", config.LLM_MODEL), ("Fallback model", config.LLM_FALLBACK_MODEL or "None"),
                    ("API address", config.LLM_BASE_URL), ("API key", mask(config.LLM_API_KEY))]
            st.markdown("".join(f'<div class="sa-row"><div class="sa-row-meta sa-key" style="margin:0">{esc(k)}</div>'
                                f'<div class="sa-row-title" style="font-weight:500">{esc(v)}</div></div>'
                                for k, v in rows), unsafe_allow_html=True)
            st.write("")
            if st.button("Test AI connection", icon=":material/bolt:"):
                with st.spinner("Sending a tiny test message..."):
                    try:
                        reply = LLMClient().generate_text("Reply with exactly: OK")
                        st.success(f"Connected. The AI answered: {reply[:40]}", icon=":material/check_circle:")
                    except Exception as error:
                        friendly_error(error)

        with card("integrations"):
            section("Integrations", "Optional services.")
            rows = [("Website (SITE_URL)", config.SITE_URL, config.SITE_URL or "Not set"),
                    ("PageSpeed Insights", config.PAGESPEED_API_KEY, mask(config.PAGESPEED_API_KEY)),
                    ("Brave Search", config.BRAVE_SEARCH_API_KEY, mask(config.BRAVE_SEARCH_API_KEY)),
                    ("WordPress (drafts only)", config.WORDPRESS_APP_PASSWORD and config.WORDPRESS_URL,
                     config.WORDPRESS_URL or "Not set")]
            st.markdown("".join(
                f'<div class="sa-row"><div><div class="sa-row-title" style="font-weight:500">{esc(name)}</div>'
                f'<div class="sa-row-meta">{esc(shown)}</div></div>'
                f'{badge("Connected", "success") if value else badge("Not set", "neutral")}</div>'
                for name, value, shown in rows), unsafe_allow_html=True)
            if wordpress.is_configured():
                st.write("")
                if st.button("Test WordPress login", icon=":material/login:"):
                    with st.spinner("Logging in to WordPress..."):
                        try:
                            name = wordpress.check_connection()
                            st.success(f"Connected as {name}.", icon=":material/check_circle:")
                        except wordpress.WordPressError as error:
                            st.error(f"WordPress problem: {error}", icon=":material/cloud_off:")
                        except Exception as error:
                            friendly_error(error)

    with right:
        with card("rules"):
            section("SEO rules", "Change these numbers in config.py.")
            rules = [("Minimum words", config.MIN_WORDS),
                     ("Focus keyword at least", f"{config.MIN_FOCUS_KEYWORD_COUNT} times"),
                     ("Max keyword density", f"{config.MAX_KEYWORD_DENSITY_PERCENT}%"),
                     ("High-authority links", f"at least {config.MIN_EXTERNAL_LINKS}"),
                     ("FAQ questions", f"at least {config.MIN_FAQ_QUESTIONS}"),
                     ("Title length", f"up to {config.TITLE_MAX_CHARS} characters"),
                     ("Meta description", f"up to {config.META_DESCRIPTION_MAX_CHARS} characters"),
                     ("Fix rounds", f"up to {config.MAX_FIX_ROUNDS}")]
            st.markdown("".join(f'<div class="sa-row"><div class="sa-row-meta sa-key" style="margin:0">{esc(k)}</div>'
                                f'<div class="sa-row-title" style="font-weight:500">{esc(v)}</div></div>'
                                for k, v in rules), unsafe_allow_html=True)
