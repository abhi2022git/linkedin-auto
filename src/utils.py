"""
Utility functions: logging, database, deduplication, and helpers.
"""

import os
import json
import sqlite3
import logging
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional, List


# ── Data Models ──────────────────────────────────────────────────────────────

@dataclass
class Article:
    """Represents a scraped article/topic."""
    title: str
    summary: str
    url: str
    source: str
    published_date: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    category: str = "tech"
    relevance_score: float = 0.0

    def to_dict(self):
        return asdict(self)


# ── Logging Setup ────────────────────────────────────────────────────────────

def setup_logging(log_dir: str = None) -> logging.Logger:
    """Configure application logging."""
    if log_dir is None:
        log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
    
    os.makedirs(log_dir, exist_ok=True)
    
    logger = logging.getLogger("linkedin_poster")
    logger.setLevel(logging.DEBUG)
    
    # Console handler
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console_fmt = logging.Formatter(
        "%(asctime)s │ %(levelname)-8s │ %(message)s",
        datefmt="%H:%M:%S"
    )
    console.setFormatter(console_fmt)
    
    # File handler (Skip on Worker)
    if not os.getenv("CLOUDFLARE_WORKER"):
        log_file = os.path.join(log_dir, f"autoposter_{datetime.now().strftime('%Y%m%d')}.log")
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_fmt = logging.Formatter(
            "%(asctime)s │ %(levelname)-8s │ %(name)s │ %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler.setFormatter(file_fmt)
        logger.addHandler(file_handler)
    
    # SQLite handler for dashboard (WARNING+ only)
    sqlite_handler = _SQLiteLogHandler()
    sqlite_handler.setLevel(logging.WARNING)
    
    if not logger.handlers:
        logger.addHandler(console)
        logger.addHandler(file_handler)
        logger.addHandler(sqlite_handler)
    
    return logger


class _SQLiteLogHandler(logging.Handler):
    """Custom logging handler that writes WARNING+ logs to the system_logs SQLite table."""

    def emit(self, record):
        try:
            from database import write_system_log
            write_system_log(
                level=record.levelname,
                module=record.name,
                message=self.format(record) if self.formatter else record.getMessage(),
            )
        except Exception:
            pass  # Never let DB logging crash the pipeline


# ── Database Manager ─────────────────────────────────────────────────────────

class DatabaseManager:
    """SQLite database for tracking posted topics and history."""
    
    def __init__(self, db_path: str = None):
        if not os.getenv("CLOUDFLARE_WORKER"):
            if db_path is None:
                db_path = os.path.join(
                    os.path.dirname(os.path.dirname(__file__)), "data", "history.db"
                )
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
            self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """Create tables if they don't exist."""
        from database import get_db
        with get_db() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS posted_topics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    url TEXT UNIQUE,
                    source TEXT,
                    post_content TEXT,
                    model_used TEXT,
                    posted_at TEXT NOT NULL,
                    linkedin_post_id TEXT,
                    image_path TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS scrape_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scraped_at TEXT NOT NULL,
                    source_count INTEGER,
                    article_count INTEGER,
                    selected_title TEXT
                )
            """)
            conn.commit()
    
    def is_already_posted(self, url: str = None, title: str = None) -> bool:
        """Check if a topic has already been posted."""
        from database import get_db
        with get_db() as conn:
            if url:
                row = conn.execute(
                    "SELECT 1 FROM posted_topics WHERE url = ?", (url,)
                ).fetchone()
                if row:
                    return True
            if title:
                # Fuzzy match: check if a very similar title exists
                row = conn.execute(
                    "SELECT 1 FROM posted_topics WHERE title = ?", (title,)
                ).fetchone()
                if row:
                    return True
        return False
    
    def record_post(self, article: Article, post_content: str, model_used: str,
                    linkedin_post_id: str = None, image_path: str = None):
        """Record a successful post."""
        from database import get_db
        with get_db() as conn:
            conn.execute(
                """INSERT INTO posted_topics 
                   (title, url, source, post_content, model_used, posted_at, linkedin_post_id, image_path)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (article.title, article.url, article.source, post_content,
                 model_used, datetime.now(timezone.utc).isoformat(),
                 linkedin_post_id, image_path)
            )
            conn.commit()
    
    def log_scrape(self, source_count: int, article_count: int, selected_title: str = None):
        """Log a scrape run."""
        from database import get_db
        with get_db() as conn:
            conn.execute(
                """INSERT INTO scrape_log (scraped_at, source_count, article_count, selected_title)
                   VALUES (?, ?, ?, ?)""",
                (datetime.now(timezone.utc).isoformat(), source_count, article_count, selected_title)
            )
            conn.commit()
    
    def get_post_count(self) -> int:
        """Get total number of posts made."""
        from database import get_db
        with get_db() as conn:
            row = conn.execute("SELECT COUNT(*) FROM posted_topics").fetchone()
            return row[0] if row else 0
    
    def get_last_model_used(self) -> Optional[str]:
        """Get the model used in the last post (for rotation)."""
        from database import get_db
        with get_db() as conn:
            row = conn.execute(
                "SELECT model_used FROM posted_topics ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return row[0] if row else None


# ── Config Loader ────────────────────────────────────────────────────────────

def load_sources(config_path: str = None) -> dict:
    """Load RSS sources configuration."""
    if config_path is None:
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "config", "sources.json"
        )
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_project_root() -> Path:
    """Get the project root directory."""
    return Path(__file__).parent.parent
