# SEO Rules This Agent Enforces

Every rule is checked by **plain Python code** in
[`src/validators/seo_rules.py`](../src/validators/seo_rules.py), not by an AI. These checks have exact answers,
so code is free, fast and gives the same result every time.

Each rule returns **PASS**, **FAIL** (with a reason and a fix hint) or **SKIP** (the rule doesn't apply,
e.g. a page with no main page has no internal-link requirement). A blog *passes* when no rule fails.

All numbers live in [`config.py`](../config.py), so you can change them in one place.

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `MIN_WORDS` | 1000 | Minimum article length |
| `MIN_FOCUS_KEYWORD_COUNT` | 5 | Focus keyword must appear at least this often |
| `MAX_KEYWORD_DENSITY_PERCENT` | 2.0 | Above this counts as keyword stuffing |
| `MIN_EXTERNAL_LINKS` | 1 | Links to high-authority sources |
| `MIN_FAQ_QUESTIONS` | 3 | Questions in the FAQ section |
| `FAQ_MAX_ANSWER_WORDS` | 80 | FAQ answers must be short and direct |
| `META_DESCRIPTION_MAX_CHARS` | 160 | Longer descriptions get cut off in Google |
| `TITLE_MAX_CHARS` | 60 | Longer titles get cut off in Google |
| `MIN_H2_HEADINGS` | 2 | A real structure needs sections |
| `FIRST_WORDS_WINDOW` | 100 | Keyword must appear in the first N words |
| `MAX_FIX_ROUNDS` | 3 | Writer <-> reviewer loop limit |
| `AUDIENCE_MIN_READING_EASE` | beginner 60, student 50, ... | Reading level per audience |

## The on-page rules

| # | Rule (rule_id) | What is checked | Why it matters |
|---|---|---|---|
| 1 | `keyword_in_title` | Focus keyword in the **title tag** and the **H1** | The strongest on-page relevance signals |
| 2 | `keyword_in_intro` | Keyword in the **first 100 words** (after the H1) | Confirms the topic to readers and search engines immediately |
| 3 | `keyword_in_h2` | Keyword in **at least one H2** | Headings describe the structure of the page |
| 4 | `keyword_in_meta_description` | Keyword in the **meta description** | Google bolds matching words in results, which improves clicks |
| 5 | `keyword_in_slug` | Keyword (hyphenated) in the **URL slug** | Short, descriptive URLs help users and rankings |
| 6 | `image_alt_keyword` | Feature image has **alt text containing the keyword** | Accessibility, and image search |
| 7 | `title_length` | Title tag is 1-60 characters | Avoids titles cut off with "..." |
| 8 | `meta_description_length` | Meta description is 1-160 characters | Avoids descriptions cut off |
| 9 | `min_word_count` | At least 1000 words | Enough depth to fully answer the topic |
| 10 | `keyword_min_count` | Keyword used at least 5 times | Clear topical focus |
| 11 | `keyword_density` | Keyword density at most 2% | Prevents keyword stuffing, which can be penalised |
| 12 | `secondary_keywords` | Each secondary keyword used at least once | Covers related searches naturally |
| 13 | `single_h1` | **Exactly one H1** | One clear main heading per page |
| 14 | `heading_structure` | Starts with H1, never skips a level (H2 to H4), at least 2 H2s | A logical outline for readers, screen readers and crawlers |
| 15 | `authority_link` | At least 1 link to a **high-authority** site (.gov, .edu, official docs, Wikipedia, major publishers; list in `config.AUTHORITY_DOMAINS`) | Shows the content is backed by trusted sources |
| 16 | `external_links_live` | Every external link responds with **HTTP 200** | Dead or invented links hurt trust (runs when link checking is on) |
| 17 | `faq_section` | `## Frequently Asked Questions` is the **last** section, with at least 3 `### question?` headings | FAQs answer real questions; good for AI search and answer engines |
| 18 | `faq_answers_short` | Each FAQ answer is 1-80 words | Short, direct answers are what answer engines quote |
| 19 | `internal_links` | A child page links to its **main page**; a main page links to **every child page** | Spreads authority and helps users navigate the topic cluster |
| 20 | `descriptive_anchors` | No "click here", "read more" or similar anchor text | Anchor text tells users and Google what the target page is about |
| 21 | `statistics_sourced` | A paragraph with a statistic (45%, 2 million, 1 in 4) contains a link | Stops invented numbers; every figure needs a source |
| 22 | `audience_reading_level` | Flesch Reading Ease at or above the target for the audience | Writing must fit the people it's for |

### How "keyword" is matched
- Case-insensitive and **whole words only** ("seo" does not match "Seoul").
- **Density** = (times used x words in keyword) / total words x 100.
  Example: "coffee grinder" used 5 times in 1000 words = 1.0%.

### What code cannot check (and how we handle it)
- **Tone** can't be measured exactly. The writer prompt asks for the right tone; code checks the
  measurable part, the **reading level**.
- **Facts** can't be verified by code. The prompts forbid invented facts, statistics and quotes; rule 21
  forces a source for any statistic; and every output carries a **"Human review required"** notice.
- **Originality**: the prompts require original writing, and the writer is only given keywords, questions
  and sources, never other sites' text to copy.

## Metadata consistency
The same focus keyword is reused in the title tag, H1, meta description, slug and image alt text
(rules 1, 4, 5 and 6). If the AI produces a slug without the keyword, code replaces it with the keyword itself.

## Technical audit checks (src/audit/checks.py)

| Issue | Priority | How it's detected |
|---|---|---|
| Page returns 404 / other error | High | Status code while crawling |
| Broken internal / external link | High | Each link checked (HEAD, then GET), retried once before being called broken |
| Exact duplicate content | High | Same SHA-256 fingerprint of the visible text |
| Near-duplicate content | Medium | 90%+ of 3-word phrases shared (Jaccard similarity) |
| Duplicate title / meta description | Medium | Same value on several pages |
| Missing title / meta description / H1 | Medium | Tag missing or empty |
| Missing image alt | Medium | `<img>` without an `alt` attribute (page and image URL listed) |
| Slow LCP / FCP | High if poor, Medium if needs improvement | PageSpeed Insights, Google's thresholds (LCP 2.5 s / 4 s, FCP 1.8 s / 3 s) |
| Multiple H1 | Low | More than one `<h1>` |
| Empty alt | Low | `alt=""` (fine for decorative images) |
| Unverified link | Low | 401/403/429/999: the site blocks bots, so check it in a browser |

## Off-page (backlink) guardrails
- Finds and drafts only. **Never** creates accounts, submits, posts, emails, or solves CAPTCHAs
  (a test in `tests/test_offpage.py` fails if such code appears).
- Rejects link sellers, "guest post services" and link farms, because paid links break Google's spam policies.
- Every item moves found -> draft -> approved -> sent, and only you can mark something sent.
