"""Tests for src/audit/checks.py using small HTML strings, never live websites."""

from src.audit import checks


def page(title="Title", description="Description", h1s=("Heading",), body="", imgs=""):
    """Build a tiny HTML page; change one argument to create a specific problem."""
    meta = f'<meta name="description" content="{description}">' if description is not None else ""
    title_tag = f"<title>{title}</title>" if title is not None else ""
    headings = "".join(f"<h1>{h}</h1>" for h in h1s)
    return f"<html><head>{title_tag}{meta}</head><body>{headings}{imgs}<p>{body}</p></body></html>"


LONG_TEXT = " ".join(f"word{i}" for i in range(200))   # 200 unique words


# --- reading HTML ---------------------------------------------------------------
def test_visible_text_ignores_scripts_and_styles():
    html = "<p>Hello World</p><script>var x = 1;</script><style>p {color: red}</style>"
    assert checks.visible_text(html) == "hello world"


def test_similarity():
    assert checks.similarity("the cat sat on the mat", "the cat sat on the mat") == 1.0
    assert checks.similarity("the cat sat on the mat", "a dog ran in the park") == 0.0


# --- duplicates -----------------------------------------------------------------
def test_exact_duplicate_content_is_found():
    pages = {"https://a.com/1": page(body=LONG_TEXT), "https://a.com/2": page(body=LONG_TEXT)}
    issues = checks.find_duplicate_content(pages)
    assert [(i.issue_type, i.page_url) for i in issues] == [("duplicate_content", "https://a.com/2")]
    assert issues[0].severity == "high"


def test_near_duplicate_content_is_found():
    almost = LONG_TEXT.replace("word199", "different")   # one word changed
    pages = {"https://a.com/1": page(body=LONG_TEXT), "https://a.com/2": page(body=almost)}
    issues = checks.find_duplicate_content(pages)
    assert [i.issue_type for i in issues] == ["near_duplicate_content"]


def test_different_pages_are_not_duplicates():
    other = " ".join(f"other{i}" for i in range(200))
    pages = {"https://a.com/1": page(body=LONG_TEXT), "https://a.com/2": page(body=other)}
    assert checks.find_duplicate_content(pages) == []


def test_short_pages_are_skipped_in_duplicate_check():
    pages = {"https://a.com/1": page(body="Contact us"), "https://a.com/2": page(body="Contact us")}
    assert checks.find_duplicate_content(pages) == []


def test_duplicate_titles_and_descriptions():
    pages = {"https://a.com/1": page(title="Home", description="Same"),
             "https://a.com/2": page(title="home", description="Same"),
             "https://a.com/3": page(title="About", description="Unique")}
    titles = checks.find_duplicate_titles(pages)
    assert sorted(i.page_url for i in titles) == ["https://a.com/1", "https://a.com/2"]
    descriptions = checks.find_duplicate_meta_descriptions(pages)
    assert len(descriptions) == 2


# --- basic tags -----------------------------------------------------------------
def test_good_page_has_no_basic_tag_issues():
    assert checks.check_basic_tags("u", page()) == []


def test_missing_title_description_and_h1():
    issues = checks.check_basic_tags("u", page(title=None, description=None, h1s=()))
    assert sorted(i.issue_type for i in issues) == ["missing_h1", "missing_meta_description",
                                                    "missing_title"]


def test_multiple_h1():
    issues = checks.check_basic_tags("u", page(h1s=("One", "Two")))
    assert [i.issue_type for i in issues] == ["multiple_h1"]


# --- images ---------------------------------------------------------------------
def test_missing_and_empty_alt_text():
    imgs = ('<img src="/ok.jpg" alt="A cat">'
            '<img src="/missing.jpg">'
            '<img src="/empty.jpg" alt="  ">')
    issues = checks.find_missing_alt("https://a.com/", page(imgs=imgs))
    assert [(i.issue_type, i.severity) for i in issues] == [("missing_alt", "medium"),
                                                             ("empty_alt", "low")]
    assert "/missing.jpg" in issues[0].detail   # the report lists the image URL


# --- status codes and links -------------------------------------------------------
def test_error_pages():
    issues = checks.find_error_pages({"https://a.com/": 200, "https://a.com/gone": 404,
                                      "https://a.com/crash": 500, "https://a.com/slow": None})
    assert sorted((i.page_url, i.issue_type) for i in issues) == [
        ("https://a.com/crash", "page_error"), ("https://a.com/gone", "page_404"),
        ("https://a.com/slow", "page_error")]


def test_broken_internal_and_external_links_with_fake_checker():
    links = {"https://a.com/": ["https://a.com/about", "https://a.com/missing",
                                "https://ext.com/dead", "https://ext.com/ok",
                                "https://linkedin.com/x"]}
    fake_statuses = {"https://a.com/missing": 404, "https://ext.com/dead": None,
                     "https://ext.com/ok": 200, "https://linkedin.com/x": 999}
    checked_urls = []

    def fake_checker(url):
        checked_urls.append(url)
        return fake_statuses[url]

    issues, count = checks.find_broken_links(
        links, "a.com", known_statuses={"https://a.com/about": 200}, link_checker=fake_checker)

    kinds = sorted((i.issue_type, i.detail.split()[2]) for i in issues)
    assert kinds == [("broken_external_link", "https://ext.com/dead"),
                     ("broken_internal_link", "https://a.com/missing"),
                     ("unverified_link", "https://linkedin.com/x")]
    assert "https://a.com/about" not in checked_urls   # already known from the crawl
    assert count == 4


def test_external_links_can_be_skipped():
    links = {"https://a.com/": ["https://ext.com/dead"]}
    issues, count = checks.find_broken_links(links, "a.com", {}, lambda url: None,
                                             check_external=False)
    assert issues == [] and count == 0


def test_link_check_limit():
    links = {"https://a.com/": [f"https://a.com/{n}" for n in range(10)]}
    _issues, count = checks.find_broken_links(links, "a.com", {}, lambda url: 200, max_checks=3)
    assert count == 3
