-- LinkedIn Auto-Poster Schema for Cloudflare D1

CREATE TABLE IF NOT EXISTS posted_topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    url TEXT UNIQUE,
    source TEXT,
    post_content TEXT,
    model_used TEXT,
    posted_at TEXT NOT NULL,
    linkedin_post_id TEXT,
    image_path TEXT,
    platform TEXT DEFAULT 'linkedin',
    status TEXT DEFAULT 'published',
    post_style TEXT,
    char_count INTEGER,
    image_theme TEXT,
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    user_id INTEGER
);

CREATE TABLE IF NOT EXISTS scrape_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scraped_at TEXT NOT NULL,
    source_count INTEGER,
    article_count INTEGER,
    selected_title TEXT,
    platform TEXT DEFAULT 'linkedin',
    user_id INTEGER
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

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
);

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
);

CREATE TABLE IF NOT EXISTS system_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    level TEXT NOT NULL,
    module TEXT,
    message TEXT NOT NULL,
    platform TEXT DEFAULT 'linkedin',
    created_at TEXT NOT NULL,
    user_id INTEGER
);

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
    created_at TEXT NOT NULL,
    user_id INTEGER
);
