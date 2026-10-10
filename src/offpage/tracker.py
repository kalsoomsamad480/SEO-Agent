"""CSV tracker for backlink opportunities: outputs/outreach/backlink_tracker.csv

A CSV file opens in Excel or Google Sheets, so you can also read and sort it there.
(If you edit it in Excel, save it as CSV again.)

Status flow. Only these moves are allowed, so nothing can skip your review:
    found    -> draft (a pitch was drafted) or rejected
    draft    -> approved (you reviewed it) or rejected
    approved -> sent (YOU sent it manually) or back to draft
    rejected -> found (changed your mind)
The program never sends or submits anything. "sent" only records what you did.
"""

import csv
import hashlib
from datetime import date

import config
from src.models.schemas import Opportunity
from src.utils.logger import get_logger

logger = get_logger(__name__)

COLUMNS = list(Opportunity.model_fields)   # the CSV header = the model's field names
ALLOWED_MOVES = {
    "found": {"draft", "rejected"},
    "draft": {"approved", "rejected"},
    "approved": {"sent", "draft", "rejected"},
    "sent": set(),
    "rejected": {"found"},
}


def make_id(url: str, blog_slug: str) -> str:
    """A short, stable ID (same url + blog always gives the same ID)."""
    return hashlib.sha1(f"{url}|{blog_slug}".encode("utf-8")).hexdigest()[:8]


def today() -> str:
    return date.today().isoformat()


def load_tracker() -> list[Opportunity]:
    """Read every row from the CSV (empty list if the file doesn't exist yet)."""
    if not config.TRACKER_FILE.is_file():
        return []
    # utf-8-sig also reads files that Excel saved with a hidden "BOM" marker.
    with open(config.TRACKER_FILE, newline="", encoding="utf-8-sig") as file:
        rows = list(csv.DictReader(file))
    try:
        return [Opportunity(**row) for row in rows]
    except ValueError as error:
        raise ValueError(f"{config.TRACKER_FILE} has an invalid row ({error}). "
                         "Fix it in a text editor or Excel, then try again.") from None


def save_tracker(items: list[Opportunity]) -> None:
    """Write all rows back to the CSV."""
    config.TRACKER_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(config.TRACKER_FILE, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(item.model_dump() for item in items)


def add_opportunities(new_items: list[Opportunity]) -> list[Opportunity]:
    """Add new rows, skipping ones already tracked. Returns only the rows actually added."""
    items = load_tracker()
    known_ids = {item.id for item in items}
    added = [item for item in new_items if item.id not in known_ids]
    save_tracker(items + added)
    logger.info("Tracker: %d new opportunit(ies) added, %d already tracked.",
                len(added), len(new_items) - len(added))
    return added


def update_item(item_id: str, **changes: str) -> Opportunity:
    """Change fields of one row (status changes must follow ALLOWED_MOVES)."""
    items = load_tracker()
    for index, item in enumerate(items):
        if item.id == item_id:
            new_status = changes.get("status")
            if new_status and new_status != item.status and new_status not in ALLOWED_MOVES[item.status]:
                allowed = ", ".join(sorted(ALLOWED_MOVES[item.status])) or "nothing (final)"
                raise ValueError(f"Can't move '{item.id}' from '{item.status}' to '{new_status}'. "
                                 f"Allowed: {allowed}.")
            items[index] = item.model_copy(update={**changes, "date": today()})
            save_tracker(items)
            return items[index]
    raise ValueError(f"No opportunity with id '{item_id}'. Run 'python main.py tracker' to see the ids.")


def format_table(items: list[Opportunity]) -> str:
    """A plain-text table for the console."""
    if not items:
        return "The tracker is empty. Run: python main.py outreach --blog outputs/blogs/<slug>"
    lines = [f"{'ID':<9}{'STATUS':<10}{'CATEGORY':<20}{'REL':>5}  OPPORTUNITY / URL"]
    for item in sorted(items, key=lambda i: (i.blog_slug, -i.relevance)):
        lines.append(f"{item.id:<9}{item.status:<10}{item.category:<20}{item.relevance:>5.2f}  "
                     f"{item.opportunity[:45]}  {item.url}")
    return "\n".join(lines)
