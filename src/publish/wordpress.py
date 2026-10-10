"""Send a finished blog to WordPress as a DRAFT (never published).

How it works:
    1. Read the saved blog folder (post.md, meta.json, validation_report.json).
    2. Turn the Markdown into HTML. The H1 is removed because WordPress shows
       the post title itself; the meta description goes into the excerpt.
    3. POST it to the WordPress REST API (/wp-json/wp/v2/posts) with
       "status": "draft". You then review it in WP Admin and press Publish yourself.

Safety rules (tests check these):
    - The status is ALWAYS "draft". There is no option to publish.
    - Login uses an Application Password from .env (WP Admin -> Users -> Profile
      -> Application Passwords), never your normal login password.
    - Credentials are only sent over HTTPS (http is allowed for localhost only).
    - Blogs that failed the SEO checks are refused unless you confirm again.
    - The caller (CLI or web app) must ask for confirmation before sending.
    - An existing post is only updated when it is still a draft.

What is NOT sent: the JSON-LD structured data (WordPress strips <script> tags;
use an SEO plugin such as Yoast or Rank Math for that) and local images
(upload them in WordPress and swap the links).
"""

import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import markdown
import requests
from bs4 import BeautifulSoup

import config
from src.utils import text_tools as tt
from src.utils.logger import get_logger

logger = get_logger(__name__)

DRAFT_STATUS = "draft"            # the only status this module ever sends
RECORD_FILE = "wordpress.json"    # saved in the blog folder after a successful send
LOCAL_HOSTS = ("localhost", "127.0.0.1")


class WordPressError(Exception):
    """A WordPress problem the user can fix (bad login, wrong URL, post not a draft, ...)."""


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
def is_configured() -> bool:
    return bool(config.WORDPRESS_URL and config.WORDPRESS_USERNAME and config.WORDPRESS_APP_PASSWORD)


def get_settings() -> tuple[str, tuple[str, str]]:
    """Return (site address, (username, app password)), or raise a friendly ConfigError."""
    missing = [name for name, value in (("WORDPRESS_URL", config.WORDPRESS_URL),
                                        ("WORDPRESS_USERNAME", config.WORDPRESS_USERNAME),
                                        ("WORDPRESS_APP_PASSWORD", config.WORDPRESS_APP_PASSWORD))
               if not value.strip()]
    if missing:
        raise config.ConfigError(
            f"WordPress is not set up. Add {', '.join(missing)} to .env "
            "(use an Application Password from WP Admin -> Users -> Profile)."
        )
    site = config.WORDPRESS_URL.strip().rstrip("/")
    parsed = urlparse(site)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise config.ConfigError(f"WORDPRESS_URL '{site}' is not a web address. Example: https://myblog.com")
    if parsed.scheme == "http" and parsed.hostname not in LOCAL_HOSTS:
        raise config.ConfigError(
            "WORDPRESS_URL must start with https:// so your password is not sent in plain text "
            "(http is only allowed for localhost)."
        )
    return site, (config.WORDPRESS_USERNAME.strip(), config.WORDPRESS_APP_PASSWORD.strip())


# ---------------------------------------------------------------------------
# Building the post
# ---------------------------------------------------------------------------
def load_post(folder: Path) -> dict:
    """Read a saved blog folder and return everything needed to send it."""
    meta_file = folder / "meta.json"
    post_file = folder / "post.md"
    if not meta_file.is_file() or not post_file.is_file():
        raise FileNotFoundError(f"No meta.json/post.md in {folder}. Pass a folder from outputs/blogs/.")
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    _settings, body = tt.split_front_matter(post_file.read_text(encoding="utf-8"))

    report_file = folder / "validation_report.json"
    report = json.loads(report_file.read_text(encoding="utf-8")) if report_file.is_file() else {}

    # WordPress prints the title as the page's H1, so drop ours to avoid two H1s.
    body = re.sub(r"\A\s*#\s+[^\n]*\n", "", body, count=1)
    content = markdown.markdown(body, extensions=["extra"])
    local_images = [img.get("src", "") for img in BeautifulSoup(content, "html.parser").find_all("img")
                    if not img.get("src", "").startswith(("http://", "https://"))]
    return {
        "title": meta["title"],
        "slug": meta["slug"],
        "excerpt": meta.get("meta_description", ""),
        "content": content,
        "passed": bool(report.get("passed")),
        "score": report.get("score", "no report"),
        "local_images": local_images,
    }


def build_payload(post: dict) -> dict:
    """The JSON body for the REST API. The status is fixed to draft."""
    return {"title": post["title"], "slug": post["slug"], "excerpt": post["excerpt"],
            "content": post["content"], "status": DRAFT_STATUS}


# ---------------------------------------------------------------------------
# Talking to WordPress
# ---------------------------------------------------------------------------
def _request(method: str, path: str, **kwargs) -> dict | list:
    """Call the REST API and turn HTTP problems into clear WordPressErrors."""
    site, auth = get_settings()
    url = f"{site}/wp-json/wp/v2/{path}"
    try:
        response = requests.request(method, url, auth=auth, timeout=config.HTTP_TIMEOUT_SECONDS,
                                    headers={"User-Agent": config.USER_AGENT}, **kwargs)
    except requests.RequestException as error:
        raise WordPressError(f"Could not reach {site}: {error}") from error

    if response.status_code == 401:
        raise WordPressError("WordPress rejected the login. Check WORDPRESS_USERNAME and "
                             "WORDPRESS_APP_PASSWORD (an Application Password, not your login password).")
    if response.status_code == 403:
        raise WordPressError("This WordPress user is not allowed to create posts. Use an Author, "
                             "Editor or Administrator account.")
    if response.status_code == 404:
        raise WordPressError(f"Not found: {url}. Check WORDPRESS_URL and that the REST API is enabled.")
    if response.status_code >= 400:
        raise WordPressError(f"WordPress answered HTTP {response.status_code}: {response.text[:200]}")
    try:
        return response.json()
    except ValueError as error:
        raise WordPressError(f"{url} did not return JSON. Is WORDPRESS_URL a WordPress site?") from error


def check_connection() -> str:
    """Log in and return the WordPress user's display name."""
    user = _request("GET", "users/me", params={"context": "edit"})
    return user.get("name") or user.get("slug") or "unknown user"


def load_record(folder: Path) -> dict:
    """The saved result of an earlier send, or {} if this blog was never sent."""
    record_file = folder / RECORD_FILE
    if not record_file.is_file():
        return {}
    return json.loads(record_file.read_text(encoding="utf-8"))


def edit_link(post_id: int) -> str:
    site, _auth = get_settings()
    return f"{site}/wp-admin/post.php?post={post_id}&action=edit"


def send_draft(folder: Path, update: bool = False, allow_failed: bool = False) -> dict:
    """Create (or, with update=True, refresh) the WordPress draft for one blog.

    The caller must have asked the user for confirmation first.
    Returns the saved record: post id, edit link and time.
    """
    post = load_post(folder)
    if not post["passed"] and not allow_failed:
        raise ValueError(f"'{post['title']}' did not pass the SEO checks ({post['score']}). "
                         "Fix it first, or confirm that you want to send it anyway.")

    record = load_record(folder)
    payload = build_payload(post)
    if record and update:
        current = _request("GET", f"posts/{record['post_id']}", params={"context": "edit"})
        if current.get("status") != DRAFT_STATUS:
            raise WordPressError(f"Post {record['post_id']} is '{current.get('status')}', not a draft. "
                                 "It will not be changed. Edit it in WordPress instead.")
        result = _request("POST", f"posts/{record['post_id']}", json=payload)
    elif record:
        raise WordPressError(f"This blog was already sent as post {record['post_id']} "
                             f"({record['edit_link']}). Use update to refresh that draft.")
    else:
        existing = _request("GET", "posts", params={"slug": post["slug"], "status": "any",
                                                    "context": "edit"})
        if existing:
            raise WordPressError(f"WordPress already has a post with the slug '{post['slug']}' "
                                 f"(post {existing[0]['id']}). Rename or delete it first.")
        result = _request("POST", "posts", json=payload)

    record = {"post_id": result["id"], "status": result.get("status", DRAFT_STATUS),
              "edit_link": edit_link(result["id"]), "sent_at": datetime.now().isoformat(timespec="seconds")}
    (folder / RECORD_FILE).write_text(json.dumps(record, indent=2), encoding="utf-8")
    logger.info("Sent '%s' to WordPress as draft %s", post["title"], result["id"])
    return record
