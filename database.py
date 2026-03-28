"""
Dashboard Database: Migrations, connections, and query functions.
Extends the existing SQLite DB with dashboard-specific tables and columns.
"""

import os
import sys
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, PROJECT_ROOT)

# --- Database Configuration ---
DB_PATH = os.path.join(PROJECT_ROOT, "data", "history.db")
SOURCES_JSON = os.path.join(PROJECT_ROOT, "config", "sources.json")

# This will store the bindings if running in a worker
_d1_binding = None
_r2_binding = None

def set_d1_binding(binding):
    """Set the D1 binding (called from main.py middleware)."""
    global _d1_binding
    _d1_binding = binding

def set_r2_binding(binding):
    """Set the R2 binding (called from main.py middleware)."""
    global _r2_binding
    _r2_binding = binding

class D1Cursor:
    """Mock sqlite3.Cursor for D1."""
    def __init__(self, result):
        self._rows = result.get("results", []) if isinstance(result, dict) else result
        self._pos = 0
        self.lastrowid = getattr(result, "meta", {}).get("last_row_id") if hasattr(result, "meta") else None
    
    def fetchone(self):
        if self._pos < len(self._rows):
            res = self._rows[self._pos]
            self._pos += 1
            return res
        return None
    
    def fetchall(self):
        return self._rows

class D1Connection:
    """Mock sqlite3.Connection for D1."""
    def __init__(self, binding):
        self.binding = binding
        self.row_factory = None
    
    def execute(self, sql, params=()):
        # Convert sqlite3 '?' to D1 style if needed (D1 supports '?')
        # D1 .prepare().bind().run() returns a result object
        res = self.binding.prepare(sql).bind(*params).run()
        return D1Cursor(res)
    
    def commit(self):
        pass
    
    def close(self):
        pass

@contextmanager
def get_db():
    """Context manager for database connections (Isomorphic Local/D1)."""
    if _d1_binding:
        yield D1Connection(_d1_binding)
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()


def init_db():
    """Run all migrations safely. Called at FastAPI startup."""
    with get_db() as conn:
        # --- Extend existing tables (ALTER TABLE, safe with try/except) ---
        alter_statements = [
            "ALTER TABLE posted_topics ADD COLUMN platform TEXT DEFAULT 'linkedin'",
            "ALTER TABLE posted_topics ADD COLUMN status TEXT DEFAULT 'published'",
            "ALTER TABLE posted_topics ADD COLUMN post_style TEXT",
            "ALTER TABLE posted_topics ADD COLUMN char_count INTEGER",
            "ALTER TABLE posted_topics ADD COLUMN image_theme TEXT",
            "ALTER TABLE posted_topics ADD COLUMN error_message TEXT",
            "ALTER TABLE posted_topics ADD COLUMN retry_count INTEGER DEFAULT 0",
            "ALTER TABLE scrape_log ADD COLUMN platform TEXT DEFAULT 'linkedin'",
            "ALTER TABLE pipeline_runs ADD COLUMN user_id INTEGER",
            "ALTER TABLE posted_topics ADD COLUMN user_id INTEGER",
            "ALTER TABLE scrape_log ADD COLUMN user_id INTEGER",
            "ALTER TABLE system_logs ADD COLUMN user_id INTEGER",
            "ALTER TABLE sources_config ADD COLUMN user_id INTEGER",
        ]
        for stmt in alter_statements:
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError:
                pass  # Column already exists

        # --- Create new tables ---
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,
                groq_api_key TEXT,
                huggingface_api_key TEXT,
                openrouter_api_key TEXT,
                linkedin_client_id TEXT,
                linkedin_client_secret TEXT,
                linkedin_access_token TEXT,
                post_schedule_hour INTEGER DEFAULT 9,
                post_schedule_minute INTEGER DEFAULT 0,
                preferred_model TEXT DEFAULT 'auto',
                enable_image_generation INTEGER DEFAULT 1,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS pipeline_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                platform TEXT NOT NULL DEFAULT 'linkedin',
                started_at TEXT NOT NULL,
                completed_at TEXT,
                status TEXT NOT NULL,
                article_title TEXT,
                article_source TEXT,
                article_url TEXT,
                model_used TEXT,
                post_char_count INTEGER,
                image_generated INTEGER,
                image_theme TEXT,
                linkedin_post_id TEXT,
                error_message TEXT,
                duration_seconds REAL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS system_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                level TEXT NOT NULL,
                module TEXT,
                message TEXT NOT NULL,
                platform TEXT DEFAULT 'linkedin',
                created_at TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS sources_config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL DEFAULT 'linkedin',
                name TEXT NOT NULL,
                url TEXT NOT NULL,
                source_type TEXT DEFAULT 'rss',
                category TEXT,
                enabled INTEGER DEFAULT 1,
                last_scraped_at TEXT,
                last_article_count INTEGER,
                created_at TEXT NOT NULL
            )
        """)

        # Set platform='linkedin' on all existing rows where platform IS NULL
        conn.execute("UPDATE posted_topics SET platform='linkedin' WHERE platform IS NULL")
        conn.execute("UPDATE posted_topics SET status='published' WHERE status IS NULL")
        conn.execute("UPDATE scrape_log SET platform='linkedin' WHERE platform IS NULL")

        # Populate sources_config from sources.json if empty
        row = conn.execute("SELECT COUNT(*) FROM sources_config").fetchone()
        if row[0] == 0:
            _populate_sources(conn)

        conn.commit()


def _populate_sources(conn):
    """Populate sources_config from config/sources.json."""
    if not os.path.exists(SOURCES_JSON):
        return
    with open(SOURCES_JSON, "r", encoding="utf-8") as f:
        config = json.load(f)

    now = datetime.now(timezone.utc).isoformat()
    for src in config.get("sources", []):
        conn.execute(
            """INSERT INTO sources_config (platform, name, url, source_type, category, enabled, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("linkedin", src["name"], src["url"], src.get("type", "rss"),
             src.get("category", "tech"), 1 if src.get("enabled", True) else 0, now)
        )


# ── Pipeline Run Tracking ────────────────────────────────────────────────────

def log_pipeline_run_start(platform: str = "linkedin", user_id: int = None) -> int:
    """Record a pipeline run start. Returns the run ID."""
    with get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO pipeline_runs (platform, started_at, status, user_id) VALUES (?, ?, ?, ?)",
            (platform, datetime.now(timezone.utc).isoformat(), "running", user_id)
        )
        conn.commit()
        return cursor.lastrowid


def log_pipeline_run_complete(run_id: int, status: str = "success", **kwargs):
    """Update a pipeline run with completion data."""
    now = datetime.now(timezone.utc).isoformat()
    fields = ["completed_at = ?", "status = ?"]
    values = [now, status]

    for key in ("article_title", "article_source", "article_url", "model_used",
                "post_char_count", "image_generated", "image_theme",
                "linkedin_post_id", "error_message", "duration_seconds"):
        if key in kwargs and kwargs[key] is not None:
            fields.append(f"{key} = ?")
            values.append(kwargs[key])

    values.append(run_id)
    sql = f"UPDATE pipeline_runs SET {', '.join(fields)} WHERE id = ?"

    with get_db() as conn:
        conn.execute(sql, values)
        conn.commit()


# ── System Log Writing ───────────────────────────────────────────────────────

def write_system_log(level: str, module: str, message: str, platform: str = "linkedin"):
    """Write a log entry to the system_logs table."""
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO system_logs (level, module, message, platform, created_at) VALUES (?, ?, ?, ?, ?)",
                (level, module, message, platform, datetime.now(timezone.utc).isoformat())
            )
            conn.commit()
    except Exception:
        pass  # Never let logging crash the pipeline


# ── Overview Queries ─────────────────────────────────────────────────────────

def get_overview() -> Dict[str, Any]:
    """Get overview stats for the dashboard home."""
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM posted_topics").fetchone()[0]

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        posts_today = conn.execute(
            "SELECT COUNT(*) FROM posted_topics WHERE posted_at LIKE ?", (f"{today}%",)
        ).fetchone()[0]

        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        posts_week = conn.execute(
            "SELECT COUNT(*) FROM posted_topics WHERE posted_at >= ?", (week_ago,)
        ).fetchone()[0]

        failed = conn.execute(
            "SELECT COUNT(*) FROM posted_topics WHERE status = 'failed'"
        ).fetchone()[0]
        success_rate = round((total - failed) / total * 100, 1) if total > 0 else 0.0

        last_post = conn.execute(
            "SELECT title, posted_at, platform, linkedin_post_id FROM posted_topics ORDER BY id DESC LIMIT 1"
        ).fetchone()

        sources_count = conn.execute(
            "SELECT COUNT(*) FROM sources_config WHERE enabled = 1"
        ).fetchone()[0]

        return {
            "total_posts": total,
            "posts_today": posts_today,
            "posts_this_week": posts_week,
            "success_rate": success_rate,
            "last_post": _format_last_post(last_post) if last_post else None,
            "next_scheduled": _get_next_scheduled(),
            "scheduler_status": "configured",
            "active_sources": sources_count,
        }


def _format_last_post(row) -> Dict:
    linkedin_id = row["linkedin_post_id"]
    linkedin_url = None
    if linkedin_id:
        linkedin_url = f"https://www.linkedin.com/feed/update/{linkedin_id}/"
    return {
        "title": row["title"],
        "posted_at": row["posted_at"],
        "platform": row["platform"] or "linkedin",
        "linkedin_url": linkedin_url,
    }


def _get_next_scheduled() -> str:
    """Calculate next scheduled run time."""
    from dotenv import load_dotenv
    load_dotenv(os.path.join(PROJECT_ROOT, "config", ".env"))
    hour = int(os.getenv("POST_SCHEDULE_HOUR", "9"))
    minute = int(os.getenv("POST_SCHEDULE_MINUTE", "0"))
    now = datetime.now()
    next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if next_run <= now:
        next_run += timedelta(days=1)
    return next_run.isoformat()


# ── Posts Queries ────────────────────────────────────────────────────────────

def get_posts(platform: str = None, status: str = None,
              limit: int = 20, offset: int = 0) -> List[Dict]:
    """Get paginated posts list."""
    with get_db() as conn:
        sql = "SELECT * FROM posted_topics WHERE 1=1"
        params = []
        if platform:
            sql += " AND platform = ?"
            params.append(platform)
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(sql, params).fetchall()
        return [_format_post(dict(r)) for r in rows]


def get_post_by_id(post_id: int) -> Optional[Dict]:
    """Get a single post by ID."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM posted_topics WHERE id = ?", (post_id,)).fetchone()
        return _format_post(dict(row)) if row else None


def retry_post(post_id: int) -> bool:
    """Mark a post for retry."""
    with get_db() as conn:
        conn.execute(
            "UPDATE posted_topics SET status='pending', retry_count = COALESCE(retry_count, 0) + 1 WHERE id = ?",
            (post_id,)
        )
        conn.commit()
        return True


def _format_post(post: Dict) -> Dict:
    """Add computed fields to post dict."""
    post["platform"] = post.get("platform") or "linkedin"
    post["status"] = post.get("status") or "published"

    if post.get("linkedin_post_id"):
        post["linkedin_url"] = f"https://www.linkedin.com/feed/update/{post['linkedin_post_id']}/"
    else:
        post["linkedin_url"] = None

    if post.get("image_path"):
        filename = os.path.basename(post["image_path"])
        post["image_url"] = f"/images/{filename}"
    else:
        post["image_url"] = None

    return post


# ── Pipeline Queries ─────────────────────────────────────────────────────────

def get_pipeline_runs(limit: int = 20, platform: str = None) -> List[Dict]:
    """Get pipeline run history."""
    with get_db() as conn:
        sql = "SELECT * FROM pipeline_runs WHERE 1=1"
        params = []
        if platform:
            sql += " AND platform = ?"
            params.append(platform)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def get_pipeline_run_by_id(run_id: int) -> Optional[Dict]:
    """Get a single pipeline run by ID."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM pipeline_runs WHERE id = ?", (run_id,)).fetchone()
        return dict(row) if row else None


# ── Sources Queries ──────────────────────────────────────────────────────────

def get_sources(platform: str = None) -> List[Dict]:
    """Get all sources."""
    with get_db() as conn:
        sql = "SELECT * FROM sources_config WHERE 1=1"
        params = []
        if platform:
            sql += " AND platform = ?"
            params.append(platform)
        sql += " ORDER BY platform, category, name"
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def toggle_source(source_id: int, enabled: bool) -> bool:
    """Toggle a source on/off. Syncs to sources.json."""
    with get_db() as conn:
        conn.execute(
            "UPDATE sources_config SET enabled = ? WHERE id = ?",
            (1 if enabled else 0, source_id)
        )
        conn.commit()
    _sync_sources_to_json()
    return True


def add_source(name: str, url: str, source_type: str = "rss",
               category: str = "tech", platform: str = "linkedin") -> int:
    """Add a new source."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO sources_config (platform, name, url, source_type, category, enabled, created_at)
               VALUES (?, ?, ?, ?, ?, 1, ?)""",
            (platform, name, url, source_type, category, now)
        )
        conn.commit()
        source_id = cursor.lastrowid
    _sync_sources_to_json()
    return source_id


def _sync_sources_to_json():
    """Sync sources_config DB table back to sources.json."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT name, url, source_type, category, enabled FROM sources_config WHERE platform = 'linkedin'"
        ).fetchall()

    if not os.path.exists(SOURCES_JSON):
        return

    with open(SOURCES_JSON, "r", encoding="utf-8") as f:
        config = json.load(f)

    config["sources"] = [
        {
            "name": r["name"],
            "url": r["url"],
            "type": r["source_type"],
            "category": r["category"],
            "enabled": bool(r["enabled"]),
        }
        for r in rows
    ]

    with open(SOURCES_JSON, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)


# ── Analytics Queries ────────────────────────────────────────────────────────

def get_analytics_summary(days: int = 30, platform: str = None) -> Dict:
    """Get analytics summary data."""
    with get_db() as conn:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        where = "WHERE posted_at >= ?"
        params = [cutoff]
        if platform:
            where += " AND platform = ?"
            params.append(platform)

        # Posts per day
        rows = conn.execute(
            f"SELECT SUBSTR(posted_at, 1, 10) as date, COUNT(*) as count FROM posted_topics {where} GROUP BY date ORDER BY date",
            params
        ).fetchall()
        posts_per_day = [{"date": r["date"], "count": r["count"]} for r in rows]

        # Posts by source
        rows = conn.execute(
            f"SELECT source, COUNT(*) as count FROM posted_topics {where} GROUP BY source ORDER BY count DESC",
            params
        ).fetchall()
        posts_by_source = [{"source": r["source"], "count": r["count"]} for r in rows]

        # Posts by model
        rows = conn.execute(
            f"SELECT model_used as model, COUNT(*) as count FROM posted_topics {where} GROUP BY model_used ORDER BY count DESC",
            params
        ).fetchall()
        posts_by_model = [{"model": r["model"], "count": r["count"]} for r in rows]

        # Posts by style
        rows = conn.execute(
            f"SELECT post_style as style, COUNT(*) as count FROM posted_topics {where} AND post_style IS NOT NULL GROUP BY post_style ORDER BY count DESC",
            params
        ).fetchall()
        posts_by_style = [{"style": r["style"], "count": r["count"]} for r in rows]

        # Posts by theme
        rows = conn.execute(
            f"SELECT image_theme as theme, COUNT(*) as count FROM posted_topics {where} AND image_theme IS NOT NULL GROUP BY image_theme ORDER BY count DESC",
            params
        ).fetchall()
        posts_by_theme = [{"theme": r["theme"], "count": r["count"]} for r in rows]

        # Averages
        avg_row = conn.execute(
            f"SELECT AVG(LENGTH(post_content)) as avg_len FROM posted_topics {where}",
            params
        ).fetchone()
        avg_char = int(avg_row["avg_len"]) if avg_row["avg_len"] else 0

        total_pub = conn.execute(
            f"SELECT COUNT(*) FROM posted_topics {where} AND (status = 'published' OR status IS NULL)",
            params
        ).fetchone()[0]

        total_fail = conn.execute(
            f"SELECT COUNT(*) FROM posted_topics {where} AND status = 'failed'",
            params
        ).fetchone()[0]

        return {
            "posts_per_day": posts_per_day,
            "posts_by_source": posts_by_source,
            "posts_by_model": posts_by_model,
            "posts_by_style": posts_by_style,
            "posts_by_theme": posts_by_theme,
            "avg_char_count": avg_char,
            "total_published": total_pub,
            "total_failed": total_fail,
        }


# ── Logs Queries ─────────────────────────────────────────────────────────────

def get_system_logs(level: str = None, module: str = None, limit: int = 200) -> List[Dict]:
    """Get system logs from DB."""
    with get_db() as conn:
        sql = "SELECT * FROM system_logs WHERE 1=1"
        params = []
        if level:
            sql += " AND level = ?"
            params.append(level.upper())
        if module:
            sql += " AND module = ?"
            params.append(module)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def get_log_file_content(lines: int = 200) -> str:
    """Read today's log file."""
    log_dir = os.path.join(PROJECT_ROOT, "logs")
    today = datetime.now().strftime("%Y%m%d")
    log_file = os.path.join(log_dir, f"autoposter_{today}.log")
    if not os.path.exists(log_file):
        return "No log file found for today."
    with open(log_file, "r", encoding="utf-8") as f:
        all_lines = f.readlines()
    return "".join(all_lines[-lines:])


# ── Settings Queries ─────────────────────────────────────────────────────────

def get_settings() -> Dict:
    """Get non-sensitive config values."""
    from dotenv import load_dotenv
    load_dotenv(os.path.join(PROJECT_ROOT, "config", ".env"), override=True)

    # Check token status
    try:
        from src.linkedin_poster import TokenManager
        tm = TokenManager()
        tokens_configured = tm.has_tokens()
    except Exception:
        tokens_configured = False

    return {
        "post_schedule_hour": int(os.getenv("POST_SCHEDULE_HOUR", "9")),
        "post_schedule_minute": int(os.getenv("POST_SCHEDULE_MINUTE", "0")),
        "enable_image_generation": os.getenv("ENABLE_IMAGE_GENERATION", "true").lower() == "true",
        "preferred_model": os.getenv("PREFERRED_MODEL", "auto"),
        "post_as_organization": os.getenv("POST_AS_ORGANIZATION", "false").lower() == "true",
        "groq_key_set": bool(os.getenv("GROQ_API_KEY")),
        "linkedin_client_id_set": bool(os.getenv("LINKEDIN_CLIENT_ID")),
        "linkedin_tokens_configured": tokens_configured,
    }
