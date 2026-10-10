"""Tests for sending blogs to WordPress as drafts. Offline: the REST API is replaced with a fake."""

import json
from pathlib import Path

import pytest

import config
from src.models.schemas import BlogDraft
from src.publish import wordpress as wp
from src.publish.exporter import save_blog
from src.validators.seo_rules import validate_blog


class FakeResponse:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self._data = data
        self.text = json.dumps(data)

    def json(self):
        if self._data is None:
            raise ValueError("not json")
        return self._data


class FakeWordPress:
    """Records every request and answers like the WordPress REST API."""

    def __init__(self):
        self.calls = []
        self.posts = {}          # id -> post
        self.next_id = 101
        self.fail_with = None    # force an HTTP status for every request

    def __call__(self, method, url, auth=None, timeout=None, headers=None, params=None, json=None):
        self.calls.append({"method": method, "url": url, "auth": auth, "params": params, "json": json})
        if self.fail_with:
            return FakeResponse(self.fail_with, {"message": "error"})
        path = url.split("/wp-json/wp/v2/", 1)[1]
        if path == "users/me":
            return FakeResponse(200, {"name": "Editor Bob", "slug": "bob"})
        if path == "posts" and method == "GET":
            return FakeResponse(200, [p for p in self.posts.values() if p["slug"] == params["slug"]])
        if path == "posts" and method == "POST":
            post = {**json, "id": self.next_id}
            self.posts[self.next_id] = post
            self.next_id += 1
            return FakeResponse(201, post)
        post_id = int(path.split("/")[1])
        if method == "GET":
            return FakeResponse(200, self.posts[post_id])
        self.posts[post_id].update(json)
        return FakeResponse(200, self.posts[post_id])


@pytest.fixture
def fake_wp(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "BLOGS_DIR", tmp_path / "blogs")
    monkeypatch.setattr(config, "WORDPRESS_URL", "https://myblog.com/")
    monkeypatch.setattr(config, "WORDPRESS_USERNAME", "bob")
    monkeypatch.setattr(config, "WORDPRESS_APP_PASSWORD", "abcd efgh ijkl")
    fake = FakeWordPress()
    monkeypatch.setattr(wp.requests, "request", fake)
    return fake


def make_blog(passed: bool = True) -> Path:
    draft = BlogDraft(title="Coffee Grinder Guide", meta_description="How to pick a grinder.",
                      slug="coffee-grinder", focus_keyword="coffee grinder",
                      body_markdown="# Coffee Grinder Guide\n\n## Burr or blade\n\nText.\n\n"
                                    "![A grinder](images/coffee-grinder.jpg)")
    folder = save_blog(draft, validate_blog(draft))
    report_file = folder / "validation_report.json"
    report = json.loads(report_file.read_text(encoding="utf-8"))
    report["passed"] = passed
    report_file.write_text(json.dumps(report), encoding="utf-8")
    return folder


# --- settings -------------------------------------------------------------------
def test_missing_settings_give_a_friendly_error(monkeypatch):
    monkeypatch.setattr(config, "WORDPRESS_URL", "")
    monkeypatch.setattr(config, "WORDPRESS_USERNAME", "bob")
    monkeypatch.setattr(config, "WORDPRESS_APP_PASSWORD", "")
    assert not wp.is_configured()
    with pytest.raises(config.ConfigError, match="WORDPRESS_URL, WORDPRESS_APP_PASSWORD"):
        wp.get_settings()


@pytest.mark.parametrize("url, ok", [("https://myblog.com", True), ("http://localhost:8080", True),
                                     ("http://127.0.0.1", True), ("http://myblog.com", False),
                                     ("myblog.com", False)])
def test_password_is_only_sent_over_https(monkeypatch, url, ok):
    monkeypatch.setattr(config, "WORDPRESS_URL", url)
    monkeypatch.setattr(config, "WORDPRESS_USERNAME", "bob")
    monkeypatch.setattr(config, "WORDPRESS_APP_PASSWORD", "secret")
    if ok:
        assert wp.get_settings()[0] == url
    else:
        with pytest.raises(config.ConfigError):
            wp.get_settings()


# --- building the post ------------------------------------------------------------
def test_post_drops_h1_and_finds_local_images(fake_wp):
    post = wp.load_post(make_blog())
    assert post["title"] == "Coffee Grinder Guide"
    assert post["excerpt"] == "How to pick a grinder."
    assert "<h1>" not in post["content"] and "<h2>Burr or blade</h2>" in post["content"]
    assert post["local_images"] == ["images/coffee-grinder.jpg"]


def test_payload_status_is_always_draft():
    payload = wp.build_payload({"title": "T", "slug": "t", "excerpt": "", "content": "", "status": "publish"})
    assert payload["status"] == "draft"


def test_missing_folder_gives_friendly_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="outputs/blogs"):
        wp.load_post(tmp_path)


# --- sending ----------------------------------------------------------------------
def test_send_creates_a_draft_and_saves_a_record(fake_wp):
    folder = make_blog()
    record = wp.send_draft(folder)
    sent = [c for c in fake_wp.calls if c["method"] == "POST"]
    assert len(sent) == 1 and sent[0]["json"]["status"] == "draft"
    assert sent[0]["auth"] == ("bob", "abcd efgh ijkl")
    assert sent[0]["url"] == "https://myblog.com/wp-json/wp/v2/posts"
    assert record["post_id"] == 101
    assert record["edit_link"] == "https://myblog.com/wp-admin/post.php?post=101&action=edit"
    assert wp.load_record(folder) == record


def test_failed_blog_needs_extra_confirmation(fake_wp):
    folder = make_blog(passed=False)
    with pytest.raises(ValueError, match="did not pass"):
        wp.send_draft(folder)
    assert fake_wp.calls == []                                 # nothing was sent
    assert wp.send_draft(folder, allow_failed=True)["post_id"] == 101


def test_second_send_needs_update(fake_wp):
    folder = make_blog()
    wp.send_draft(folder)
    with pytest.raises(wp.WordPressError, match="already sent"):
        wp.send_draft(folder)
    assert wp.send_draft(folder, update=True)["post_id"] == 101
    assert len(fake_wp.posts) == 1


def test_published_post_is_never_changed(fake_wp):
    folder = make_blog()
    wp.send_draft(folder)
    fake_wp.posts[101]["status"] = "publish"                   # someone published it in WP Admin
    with pytest.raises(wp.WordPressError, match="not a draft"):
        wp.send_draft(folder, update=True)
    assert fake_wp.calls[-1]["method"] == "GET"                # no POST after the check


def test_existing_slug_is_not_overwritten(fake_wp):
    fake_wp.posts[50] = {"id": 50, "slug": "coffee-grinder", "status": "publish"}
    with pytest.raises(wp.WordPressError, match="already has a post"):
        wp.send_draft(make_blog())


@pytest.mark.parametrize("status, message", [(401, "rejected the login"), (403, "not allowed"),
                                             (404, "Not found"), (500, "HTTP 500")])
def test_http_errors_are_friendly(fake_wp, status, message):
    fake_wp.fail_with = status
    with pytest.raises(wp.WordPressError, match=message):
        wp.check_connection()


def test_check_connection_returns_user_name(fake_wp):
    assert wp.check_connection() == "Editor Bob"


def test_module_has_no_way_to_publish():
    source = Path(wp.__file__).read_text(encoding="utf-8")
    assert '"publish"' not in source and "'publish'" not in source


# --- command line -----------------------------------------------------------------
def run_cli(monkeypatch, answers, *argv):
    import main
    replies = iter(answers)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(replies))
    monkeypatch.setattr("sys.argv", ["main.py", "wordpress", *argv])
    return main.main()


def test_cli_sends_nothing_without_yes(fake_wp, monkeypatch):
    folder = make_blog()
    assert run_cli(monkeypatch, ["n"], "--blog", str(folder)) == 0
    assert not [c for c in fake_wp.calls if c["method"] == "POST"]
    assert wp.load_record(folder) == {}


def test_cli_sends_draft_after_yes(fake_wp, monkeypatch):
    folder = make_blog()
    assert run_cli(monkeypatch, ["y"], "--blog", str(folder)) == 0
    assert wp.load_record(folder)["post_id"] == 101


def test_cli_failed_blog_asks_twice(fake_wp, monkeypatch):
    folder = make_blog(passed=False)
    assert run_cli(monkeypatch, ["y", "n"], "--blog", str(folder)) == 0
    assert fake_wp.posts == {}
    assert run_cli(monkeypatch, ["y", "y"], "--blog", str(folder)) == 0
    assert fake_wp.posts[101]["status"] == "draft"


def test_cli_wordpress_error_is_friendly(fake_wp, monkeypatch):
    fake_wp.fail_with = 401
    assert run_cli(monkeypatch, [], "--check") == 1
