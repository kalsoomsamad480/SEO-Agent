"""Logging setup: every module writes to the console AND to logs/app.log.

Usage in any file:
    from src.utils.logger import get_logger
    logger = get_logger(__name__)
    logger.info("Starting research")
"""

import logging
from logging.handlers import RotatingFileHandler

import config

LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# The name of our "parent" logger. Every module logger (e.g. "seo_agent.src.content.writer")
# is a child of this one, so we only attach handlers once, here.
ROOT_LOGGER_NAME = "seo_agent"


def _setup_root_logger() -> logging.Logger:
    """Attach the console and file handlers to the project's root logger (once)."""
    root = logging.getLogger(ROOT_LOGGER_NAME)

    # Without this check, importing the logger twice would print every line twice.
    if root.handlers:
        return root

    # The logger lets everything through; each handler then decides what to keep.
    # Console shows LOG_LEVEL (normally INFO); the file keeps DEBUG too, so
    # full error details are saved for you without cluttering the screen.
    root.setLevel(logging.DEBUG)
    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)

    console = logging.StreamHandler()
    console.setLevel(config.LOG_LEVEL)
    console.setFormatter(formatter)
    root.addHandler(console)

    # Rotating file: when app.log reaches ~1 MB it is renamed to app.log.1 and a
    # new file starts, so the log folder never grows forever.
    config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_file = RotatingFileHandler(
        config.LOGS_DIR / "app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    log_file.setLevel(logging.DEBUG)
    log_file.setFormatter(formatter)
    root.addHandler(log_file)

    # Don't also pass messages to Python's global logger (avoids duplicates,
    # e.g. when Streamlit configures its own logging).
    root.propagate = False
    return root


def get_logger(name: str) -> logging.Logger:
    """Return a logger for one module. Pass `__name__` as the name."""
    _setup_root_logger()
    return logging.getLogger(f"{ROOT_LOGGER_NAME}.{name}")
