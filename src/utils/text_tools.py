"""Small, reusable text helpers: word count, keyword count, density, headings, links.

Everything here is plain Python with no network and no AI, so it is fast,
free and easy to test. The SEO validator is built on top of these helpers.

Blogs are written in Markdown, so most helpers understand Markdown syntax:
    # Heading 1        ## Heading 2        [anchor text](https://url)
    ![image alt](https://image-url)
"""

import re
from typing import NamedTuple
from urllib.parse import urlparse

# A "word" is letters/digits, optionally joined by an apostrophe or hyphen
# ("don't", "e-mail"). [^\W_] means "any letter or digit, in any language".
WORD_PATTERN = re.compile(r"[^\W_]+(?:['’-][^\W_]+)*")

HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
# (?<!!) = "not preceded by !", so images are not counted as links.
LINK_PATTERN = re.compile(r"(?<!!)\[([^\]]+)\]\((\S+?)(?:\s+\"[^\"]*\")?\)")
IMAGE_PATTERN = re.compile(r"!\[([^\]]*)\]\((\S+?)(?:\s+\"[^\"]*\")?\)")


class Heading(NamedTuple):
    """One Markdown heading, e.g. level=2, text="Why it matters"."""
    level: int
    text: str


class Link(NamedTuple):
    """One Markdown link: the clickable text and where it points."""
    anchor: str
    url: str


class Image(NamedTuple):
    """One Markdown image: its alt text and its address."""
    alt: str
    url: str


class Section(NamedTuple):
    """A heading plus the text under it (until the next heading)."""
    level: int
    title: str
    content: str


# ---------------------------------------------------------------------------
# Cleaning Markdown
# ---------------------------------------------------------------------------
def _remove_code_blocks(markdown: str) -> str:
    """Remove ```fenced code blocks``` because code is not readable prose."""
    return re.sub(r"```.*?```", " ", markdown, flags=re.DOTALL)


def markdown_to_plain_text(markdown: str) -> str:
    """Turn Markdown into plain readable text (what a visitor actually reads).

    Images disappear, links keep only their anchor text, and symbols like
    #, *, > and list bullets are removed.
    """
    text = _remove_code_blocks(markdown)
    text = IMAGE_PATTERN.sub(" ", text)
    text = LINK_PATTERN.sub(r"\1", text)
    text = re.sub(r"<[^>]+>", " ", text)                          # HTML tags
    text = re.sub(r"`([^`]*)`", r"\1", text)                       # inline code
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.MULTILINE)  # heading marks
    text = re.sub(r"^\s*>\s?", "", text, flags=re.MULTILINE)       # quotes
    text = re.sub(r"^\s*(?:[-*+]|\d+\.)\s+", "", text, flags=re.MULTILINE)  # list bullets
    text = re.sub(r"(\*{1,3}|_{2,3})", "", text)                   # bold / italic marks
    return text


# ---------------------------------------------------------------------------
# Words and keywords
# ---------------------------------------------------------------------------
def get_words(text: str) -> list[str]:
    """Split text into a list of words."""
    return WORD_PATTERN.findall(text)


def word_count(text: str) -> int:
    """Count the words in text."""
    return len(get_words(text))


def first_n_words(text: str, n: int) -> str:
    """Return the first n words of text joined by spaces."""
    return " ".join(get_words(text)[:n])


def _keyword_regex(keyword: str) -> re.Pattern:
    """Build a case-insensitive pattern that matches the keyword as whole words.

    Whole words matter: the keyword "seo" must NOT match inside "Seoul".
    Any spacing between the keyword's words is allowed.
    """
    parts = [re.escape(word) for word in keyword.split()]
    return re.compile(r"(?<!\w)" + r"\s+".join(parts) + r"(?!\w)", re.IGNORECASE)


def contains_keyword(text: str, keyword: str) -> bool:
    """True if the keyword appears at least once in text (whole words, any case)."""
    if not keyword.strip():
        return False
    return _keyword_regex(keyword).search(text) is not None


def keyword_count(text: str, keyword: str) -> int:
    """Count how many times the keyword appears in text (whole words, any case)."""
    if not keyword.strip():
        return 0
    return len(_keyword_regex(keyword).findall(text))


def keyword_density(text: str, keyword: str) -> float:
    """Percent of the text's words that belong to the keyword.

    Formula: (times used x words in keyword) / total words x 100.
    Example: "coffee grinder" used 5 times in 1000 words = 5 x 2 / 1000 x 100 = 1.0%.
    """
    total = word_count(text)
    if total == 0:
        return 0.0
    keyword_words = len(keyword.split())
    return keyword_count(text, keyword) * keyword_words / total * 100


# ---------------------------------------------------------------------------
# Headings, sections, links, images
# ---------------------------------------------------------------------------
def extract_headings(markdown: str) -> list[Heading]:
    """List every Markdown heading in order, skipping lines inside code blocks."""
    headings = []
    inside_code = False
    for line in markdown.splitlines():
        if line.strip().startswith("```"):
            inside_code = not inside_code
            continue
        if inside_code:
            continue
        match = HEADING_PATTERN.match(line.strip())
        if match:
            headings.append(Heading(level=len(match.group(1)), text=match.group(2)))
    return headings


def split_sections(markdown: str) -> list[Section]:
    """Split Markdown into sections: each heading with the text below it.

    Text before the first heading is ignored (there usually is none).
    """
    sections: list[Section] = []
    current_level, current_title, lines = 0, "", []
    inside_code = False

    def save_current() -> None:
        if current_level:
            sections.append(Section(current_level, current_title, "\n".join(lines).strip()))

    for line in markdown.splitlines():
        if line.strip().startswith("```"):
            inside_code = not inside_code
        match = None if inside_code else HEADING_PATTERN.match(line.strip())
        if match:
            save_current()
            current_level, current_title, lines = len(match.group(1)), match.group(2), []
        else:
            lines.append(line)
    save_current()
    return sections


def extract_links(markdown: str) -> list[Link]:
    """List every Markdown link [anchor](url), not counting images."""
    return [Link(anchor.strip(), url.strip()) for anchor, url in LINK_PATTERN.findall(markdown)]


def extract_images(markdown: str) -> list[Image]:
    """List every Markdown image ![alt](url)."""
    return [Image(alt.strip(), url.strip()) for alt, url in IMAGE_PATTERN.findall(markdown)]


def get_domain(url: str) -> str:
    """Return the domain of a URL without "www.", e.g. "https://www.bbc.com/x" -> "bbc.com"."""
    domain = urlparse(url).netloc.lower().split(":")[0]
    return domain.removeprefix("www.")


# ---------------------------------------------------------------------------
# Slugs and front matter
# ---------------------------------------------------------------------------
def slugify(text: str) -> str:
    """Make a URL-friendly slug: "How to Brew Coffee!" -> "how-to-brew-coffee"."""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def split_front_matter(text: str) -> tuple[dict[str, str], str]:
    """Separate an optional settings block from the top of a Markdown file.

    A file may start like this:
        ---
        focus_keyword: coffee grinder
        meta_description: Learn how to ...
        ---
        # The blog starts here

    Returns (settings dict, the rest of the text). Without a block, the dict is empty.
    """
    lines = text.lstrip("﻿").splitlines()   # ﻿ = invisible marker some editors add
    if not lines or lines[0].strip() != "---":
        return {}, text

    settings: dict[str, str] = {}
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            body = "\n".join(lines[index + 1:])
            if text.endswith("\n"):
                body += "\n"   # splitlines() drops the final newline; put it back
            return settings, body
        if ":" in line:
            key, value = line.split(":", 1)
            settings[key.strip().lower()] = value.strip()
    # No closing "---": treat the whole thing as normal text.
    return {}, text


# ---------------------------------------------------------------------------
# Readability
# ---------------------------------------------------------------------------
def split_sentences(text: str) -> list[str]:
    """Split text into sentences at . ! or ? (simple, good enough for scoring)."""
    parts = re.split(r"[.!?]+(?:\s+|$)", text)
    return [part for part in parts if get_words(part)]


def count_syllables(word: str) -> int:
    """Estimate syllables by counting vowel groups ("coffee" -> cof-fee = 2).

    English spelling is messy, so this is an estimate, but it is accurate
    enough for a readability score.
    """
    word = word.lower()
    groups = re.findall(r"[aeiouy]+", word)
    count = len(groups)
    if word.endswith("e") and not word.endswith(("le", "ee")) and count > 1:
        count -= 1   # silent "e" as in "make"
    return max(count, 1)


def flesch_reading_ease(text: str) -> float:
    """Flesch Reading Ease score: higher = easier to read.

    90-100 very easy, 60-70 plain English, 30-50 difficult, below 30 very hard.
    Formula: 206.835 - 1.015 x (words per sentence) - 84.6 x (syllables per word).
    """
    words = get_words(text)
    sentences = split_sentences(text)
    if not words or not sentences:
        return 0.0
    syllables = sum(count_syllables(word) for word in words)
    score = 206.835 - 1.015 * (len(words) / len(sentences)) - 84.6 * (syllables / len(words))
    return round(score, 1)
