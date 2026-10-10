"""Tests for src/utils/text_tools.py. Small, hard-coded examples, no internet."""

import pytest

from src.utils import text_tools as tt


# --- word count ------------------------------------------------------------
def test_word_count_simple_sentence():
    assert tt.word_count("The quick brown fox jumps.") == 5


def test_word_count_keeps_contractions_and_hyphens_as_one_word():
    assert tt.word_count("Don't use e-mail here") == 4


def test_word_count_empty_text_is_zero():
    assert tt.word_count("   ") == 0


def test_first_n_words():
    assert tt.first_n_words("one two three four", 2) == "one two"


# --- keyword count and density --------------------------------------------
def test_keyword_count_ignores_case():
    assert tt.keyword_count("SEO tips. seo basics. Seo tools.", "seo") == 3


def test_keyword_count_matches_whole_words_only():
    # "seo" must not match inside "Seoul".
    assert tt.keyword_count("I visited Seoul to learn SEO.", "seo") == 1


def test_keyword_count_multi_word_keyword():
    text = "A coffee grinder helps. My coffee  grinder is new. Coffee is nice."
    assert tt.keyword_count(text, "coffee grinder") == 2


def test_contains_keyword_empty_keyword_is_false():
    assert tt.contains_keyword("anything", "  ") is False


def test_keyword_density_formula():
    # 10 words, keyword of 2 words used once -> 2 / 10 x 100 = 20%
    text = "coffee grinder one two three four five six seven eight"
    assert tt.keyword_density(text, "coffee grinder") == pytest.approx(20.0)


def test_keyword_density_of_empty_text_is_zero():
    assert tt.keyword_density("", "seo") == 0.0


# --- markdown helpers -------------------------------------------------------
SAMPLE_MD = """# Main Title

Intro with a [helpful link](https://example.com/page) and **bold** text.

![alt words](https://example.com/img.png)

## Section One

```
# not a heading, this is code
```

### Sub Point

Text.
"""


def test_extract_headings_skips_code_blocks():
    headings = tt.extract_headings(SAMPLE_MD)
    assert [(h.level, h.text) for h in headings] == [
        (1, "Main Title"), (2, "Section One"), (3, "Sub Point"),
    ]


def test_extract_links_excludes_images():
    links = tt.extract_links(SAMPLE_MD)
    assert links == [tt.Link("helpful link", "https://example.com/page")]


def test_extract_images():
    assert tt.extract_images(SAMPLE_MD) == [tt.Image("alt words", "https://example.com/img.png")]


def test_markdown_to_plain_text_removes_symbols_and_keeps_anchor_text():
    text = tt.markdown_to_plain_text(SAMPLE_MD)
    assert "helpful link" in text
    assert "https://" not in text
    assert "**" not in text
    assert "#" not in text
    assert "alt words" not in text   # images are not visible text


def test_split_sections():
    sections = tt.split_sections(SAMPLE_MD)
    assert [s.title for s in sections] == ["Main Title", "Section One", "Sub Point"]
    assert sections[2].content == "Text."


def test_get_domain_strips_www():
    assert tt.get_domain("https://www.BBC.com/news?x=1") == "bbc.com"


def test_slugify():
    assert tt.slugify("  How to Brew Coffee! (2026) ") == "how-to-brew-coffee-2026"


# --- front matter -----------------------------------------------------------
def test_split_front_matter_reads_settings():
    settings, body = tt.split_front_matter("---\nfocus_keyword: seo tips\nslug: a-b\n---\n# Hi")
    assert settings == {"focus_keyword": "seo tips", "slug": "a-b"}
    assert body.strip() == "# Hi"


def test_split_front_matter_without_block_returns_text_unchanged():
    assert tt.split_front_matter("# Hi") == ({}, "# Hi")


# --- readability ------------------------------------------------------------
def test_count_syllables_estimates():
    assert tt.count_syllables("cat") == 1
    assert tt.count_syllables("coffee") == 2
    assert tt.count_syllables("make") == 1


def test_simple_text_is_easier_than_complex_text():
    simple = "The cat sat on the mat. It was a good day. We had fun."
    complex_text = ("Comprehensive organizational transformation necessitates "
                    "considerable interdepartmental collaboration and accountability.")
    assert tt.flesch_reading_ease(simple) > tt.flesch_reading_ease(complex_text)
