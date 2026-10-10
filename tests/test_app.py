"""Smoke tests for the Streamlit app using Streamlit's built-in AppTest (no browser, no AI calls).

The full app (sidebar menu + dashboard) is tested from app.py. Each page is also
tested on its own with AppTest.from_function, because the test tool can only
switch between file-based pages.
"""

import pytest
from streamlit.testing.v1 import AppTest

import config
from src.models.schemas import AuditIssue, AuditReport, BlogDraft, Opportunity
from src.offpage import tracker
from src.publish.exporter import save_blog
from src.validators.seo_rules import validate_blog

TIMEOUT = 30   # seconds; the first run imports pandas/streamlit, which is slow
APP_FILE = config.PROJECT_ROOT / "app.py"


@pytest.fixture(autouse=True)
def temp_outputs(monkeypatch, tmp_path):
    """Run the app against temporary folders instead of the real outputs/."""
    monkeypatch.setattr(config, "BLOGS_DIR", tmp_path / "blogs")
    monkeypatch.setattr(config, "AUDITS_DIR", tmp_path / "audits")
    monkeypatch.setattr(config, "SITE_MAP_FILE", tmp_path / "site_map.json")
    monkeypatch.setattr(config, "TRACKER_FILE", tmp_path / "tracker.csv")
    for folder in ("blogs", "audits"):
        (tmp_path / folder).mkdir()


def add_sample_data() -> None:
    """One blog, one audit and one tracker row, so every page has something to show."""
    draft = BlogDraft(title="Coffee Grinder Guide", meta_description="A guide.", slug="coffee-grinder",
                      focus_keyword="coffee grinder", body_markdown="# Coffee Grinder\n\nText.")
    save_blog(draft, validate_blog(draft))
    folder = config.AUDITS_DIR / "a.com-20260101-1200"
    folder.mkdir()
    report = AuditReport(site_url="https://a.com/", pages_crawled=2, issues=[
        AuditIssue(page_url="https://a.com/x", issue_type="page_404", severity="high", detail="404")])
    (folder / "audit.json").write_text(report.model_dump_json(), encoding="utf-8")
    tracker.add_opportunities([Opportunity(id="abc12345", opportunity="DEV Community",
                                           category="article_submission", url="https://dev.to",
                                           relevance=0.8, blog_slug="coffee-grinder")])


def run_view(view_name: str) -> AppTest:
    """Render one page function on its own and fail on any exception."""
    def script(name):
        from src.ui import components, views
        components.inject_css()
        getattr(views, name)()

    app = AppTest.from_function(script, args=(view_name,), default_timeout=TIMEOUT)
    app.run()
    assert not app.exception, app.exception
    return app


def all_markdown(app: AppTest) -> str:
    return " ".join(m.value for m in app.markdown)


# --- full app -------------------------------------------------------------------
def test_app_loads_dashboard_with_review_notice():
    app = AppTest.from_file(str(APP_FILE), default_timeout=TIMEOUT)
    app.run()
    assert not app.exception, app.exception
    text = all_markdown(app)
    assert "Dashboard" in text
    assert "Human review required" in text


# --- each page, empty and with data --------------------------------------------------
@pytest.mark.parametrize("view", ["dashboard_view", "create_blog_view", "library_view",
                                  "audit_view", "backlinks_view", "settings_view"])
def test_every_page_renders_without_data(view):
    run_view(view)


@pytest.mark.parametrize("view", ["dashboard_view", "library_view", "audit_view", "backlinks_view"])
def test_every_page_renders_with_data(view):
    add_sample_data()
    run_view(view)


def test_dashboard_counts_and_lists_blogs():
    add_sample_data()
    app = run_view("dashboard_view")
    metrics = {m.label: m.value for m in app.metric}
    assert metrics["Blog posts"] == "1"
    assert metrics["Site audits"] == "1"
    assert "Coffee Grinder Guide" in all_markdown(app)


def test_manual_form_with_empty_topic_shows_friendly_error():
    app = run_view("create_blog_view")
    app.text_input[0].set_value("")                                       # question 1: topic
    next(b for b in app.button if b.label == "Write the blog post").click().run()
    assert not app.exception
    assert any("topic can't be empty" in e.value for e in app.error)


def test_library_shows_seo_checks_table():
    add_sample_data()
    app = run_view("library_view")
    assert "Coffee Grinder Guide" in all_markdown(app)
    assert len(app.dataframe) >= 1


def test_audit_page_shows_issue_counts():
    add_sample_data()
    app = run_view("audit_view")
    assert any(m.label == "High priority" and m.value == "1" for m in app.metric)


def test_wordpress_tab_explains_setup_when_not_configured(monkeypatch):
    monkeypatch.setattr(config, "WORDPRESS_URL", "")
    add_sample_data()
    app = run_view("library_view")
    assert any("WordPress is not set up" in i.value for i in app.info)


def test_wordpress_send_needs_the_review_checkbox(monkeypatch):
    from src.publish import wordpress
    monkeypatch.setattr(config, "WORDPRESS_URL", "https://myblog.com")
    monkeypatch.setattr(config, "WORDPRESS_USERNAME", "bob")
    monkeypatch.setattr(config, "WORDPRESS_APP_PASSWORD", "secret")
    sent = []
    monkeypatch.setattr(wordpress, "send_draft", lambda folder, **kw: sent.append(kw) or {
        "post_id": 7, "edit_link": "https://myblog.com/wp-admin/post.php?post=7&action=edit"})
    add_sample_data()                     # this sample post fails the SEO checks
    app = run_view("library_view")
    send = next(b for b in app.button if b.label == "Send as draft")
    assert send.disabled
    app.checkbox(key="wp-ok-coffee-grinder").check().run()
    assert next(b for b in app.button if b.label == "Send as draft").disabled   # still needs 2nd tick
    app.checkbox(key="wp-failed-coffee-grinder").check().run()
    next(b for b in app.button if b.label == "Send as draft").click().run()
    assert not app.exception
    assert sent == [{"update": False, "allow_failed": True}]
    assert any("Saved as draft 7" in s.value for s in app.success)
