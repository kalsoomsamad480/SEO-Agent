"""The writer <-> reviewer loop: write, validate, fix, validate again.

    write article + metadata
         |
         v
    validate (plain-code SEO rules) --all pass--> done
         |
      failures
         v
    fix: send the draft + exact failure reasons to the LLM
         |
         +--> validate again ... at most MAX_FIX_ROUNDS times

If the draft still fails after the last round, we keep the BEST draft
(the one with the fewest failed rules) and report what is still failing.
A plain `for` loop with a fixed limit means it can never loop forever.
"""

from dataclasses import dataclass, field
from functools import lru_cache

import config
from src.content.metadata import create_metadata
from src.content.writer import assemble_draft, fix_blog, write_blog
from src.llm.client import LLMClient, get_client
from src.models.schemas import (BlogDraft, BlogMetadata, BlogOutline, BlogRequest,
                                KeywordPlan, ValidationReport)
from src.utils.logger import get_logger
from src.validators.seo_rules import LinkChecker, default_link_checker, validate_blog

logger = get_logger(__name__)

# Rules about the metadata (title tag, description, slug, alt text). These are fixed
# by regenerating the metadata; every other rule is fixed by rewriting the article.
METADATA_RULES = {"title_length", "meta_description_length", "keyword_in_meta_description",
                  "keyword_in_slug", "image_alt_keyword"}


@dataclass
class LoopResult:
    """What the loop returns: the best draft, its report, and how it got there."""
    draft: BlogDraft
    report: ValidationReport
    fix_rounds_used: int
    history: list[str] = field(default_factory=list)   # e.g. ["Draft: 15/21", "Round 1: 20/21"]


def _problem_lines(report: ValidationReport, metadata_only: bool = False) -> list[str]:
    """Turn failed rules into lines like 'Rule name: reason Fix: hint' for the LLM.

    metadata_only=False gives the article problems; True gives the metadata problems.
    Each fixer only sees what it can actually change.
    """
    lines = []
    for r in report.failed_rules:
        is_metadata = r.rule_id in METADATA_RULES
        if is_metadata == metadata_only or r.rule_id == "keyword_in_title":
            lines.append(f"{r.name}: {r.reason} Fix: {r.fix_hint}")
    return lines


def _needs_metadata_fix(report: ValidationReport) -> bool:
    """True if any failed rule is about metadata (including the title tag)."""
    for result in report.failed_rules:
        if result.rule_id in METADATA_RULES:
            return True
        if result.rule_id == "keyword_in_title" and "title tag" in result.reason:
            return True
    return False


def _needs_body_fix(report: ValidationReport) -> bool:
    """True if any failed rule is about the article itself."""
    return any(r.rule_id not in METADATA_RULES for r in report.failed_rules)


def _log_round(label: str, report: ValidationReport) -> str:
    """Print one line per round so you can watch the loop work."""
    line = f"{label}: {report.score}"
    logger.info(line)
    for result in report.failed_rules:
        logger.info("    FAIL %s - %s", result.name, result.reason)
    return line


def run_writer_reviewer_loop(request: BlogRequest, plan: KeywordPlan, outline: BlogOutline,
                             llm: LLMClient | None = None,
                             max_rounds: int = config.MAX_FIX_ROUNDS,
                             link_checker: LinkChecker | None = None) -> LoopResult:
    """Write the blog, then fix and re-validate until it passes or max_rounds is reached."""
    llm = llm or get_client()
    # Remember each URL's status so we don't re-check the same link every round.
    checker = lru_cache(maxsize=None)(link_checker or default_link_checker)

    body = write_blog(request, plan, outline, llm=llm)
    metadata: BlogMetadata = create_metadata(request, plan, body, llm=llm)
    draft = assemble_draft(request, plan, body, metadata)
    report = validate_blog(draft, link_checker=checker)
    history = [_log_round("First draft", report)]
    best_draft, best_report = draft, report
    rounds_used = 0

    for round_number in range(1, max_rounds + 1):
        if report.passed:
            break
        rounds_used = round_number
        logger.info("Fix round %d of %d: fixing %d problem(s)...",
                    round_number, max_rounds, len(report.failed_rules))
        if _needs_body_fix(report):
            body = fix_blog(request, plan, body, _problem_lines(report), llm=llm)
        if _needs_metadata_fix(report):
            metadata = create_metadata(request, plan, body, llm=llm,
                                       initial_problems=_problem_lines(report, metadata_only=True))

        draft = assemble_draft(request, plan, body, metadata)
        report = validate_blog(draft, link_checker=checker)
        history.append(_log_round(f"Round {round_number}", report))

        # Keep the best version: a fix can occasionally make things worse.
        if len(report.failed_rules) < len(best_report.failed_rules):
            best_draft, best_report = draft, report

    if best_report.passed:
        logger.info("All SEO rules passed after %d fix round(s).", rounds_used)
    else:
        failed = ", ".join(r.name for r in best_report.failed_rules)
        logger.warning("Stopped after %d fix round(s). Best draft still fails: %s", rounds_used, failed)
    return LoopResult(best_draft, best_report, rounds_used, history)
