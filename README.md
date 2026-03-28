# 🤖 LinkedIn Auto-Poster

Fully automated LinkedIn posting pipeline: scrapes trending tech topics, generates professional posts using LLMs, creates branded images, and publishes to LinkedIn — zero human interaction.

## ⚡ Quick Start

### 1. Install Dependencies
```bash
cd linkedin-auto-poster
pip install -r requirements.txt
```

### 2. Configure API Keys
```bash
# Copy the template
copy config\.env.example config\.env

# Edit config\.env and add:
# - GROQ_API_KEY (free from https://console.groq.com/keys)
# - LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET
#   (from https://developer.linkedin.com)
```

### 3. Set Up LinkedIn OAuth
```bash
python main.py --auth
```
This opens a browser for LinkedIn authorization. Authorize once, and the token is stored securely.

### 4. Run
```bash
# Test without posting
python main.py --dry-run

# Post once
python main.py --once

# Start daily scheduler
python main.py
```

## 🏗️ Architecture

```
Content Sources (RSS/Medium/News)
        │
        ▼
   ┌─────────┐
   │ Scraper  │ ── feedparser + BeautifulSoup
   └────┬────┘
        │ Best Article
        ▼
   ┌──────────┐
   │ Generator│ ── Groq API (Llama3/Mixtral/Gemma)
   └────┬────┘
        │ LinkedIn Post
        ▼
   ┌──────────┐
   │ Image Gen│ ── Pillow (branded gradients)
   └────┬────┘
        │
        ▼
   ┌──────────┐
   │ LinkedIn │ ── OAuth 2.0 + REST API
   │  Poster  │
   └──────────┘
```

## 🤖 Models (via Groq — Free)

| Model | Best For |
|-------|----------|
| Llama 3.3 70B | Detailed, analytical posts |
| Mixtral 8x7B | Creative, varied writing |
| Gemma 2 9B | Concise, punchy content |
| Llama 3.1 8B | Fast, engaging content |

Models auto-rotate per post. Set `PREFERRED_MODEL=auto` in `.env` or pick a specific one.

## 📰 Content Sources

Pre-configured RSS feeds (editable in `config/sources.json`):
- Hacker News, TechCrunch, The Verge, MIT Tech Review
- Towards Data Science, ArXiv (ML & AI)
- Dev.to, Google AI Blog, OpenAI Blog, VentureBeat
- Analytics Vidhya, KDnuggets, AWS ML Blog

## 🔧 CLI Commands

| Command | Description |
|---------|-------------|
| `python main.py --auth` | LinkedIn OAuth setup (run once) |
| `python main.py --dry-run` | Test pipeline, no posting |
| `python main.py --once` | Single post cycle |
| `python main.py` | Start daily scheduler |
| `python main.py --status` | View posting stats |

## 📁 Project Structure

```
linkedin-auto-poster/
├── config/
│   ├── .env.example      # Environment template
│   ├── .env              # Your actual config (git-ignored)
│   ├── sources.json      # RSS feed sources
│   └── tokens.json       # Encrypted LinkedIn tokens
├── src/
│   ├── scraper.py        # Content scraping
│   ├── content_generator.py  # LLM post generation
│   ├── image_generator.py    # Branded images
│   ├── linkedin_poster.py    # LinkedIn API
│   ├── scheduler.py      # Automation
│   └── utils.py          # Shared utilities
├── data/
│   ├── history.db        # SQLite: posted topics
│   └── images/           # Generated images
├── logs/                 # Application logs
├── auth_setup.py         # OAuth helper
├── main.py               # CLI entry point
└── requirements.txt
```

## 🔐 LinkedIn Developer Setup

1. Go to [LinkedIn Developer Portal](https://developer.linkedin.com)
2. Create an app (associate with a LinkedIn page)
3. Under **Products**, request **"Share on LinkedIn"**
4. Copy **Client ID** and **Client Secret** to `config/.env`
5. Add both `http://localhost:8080/callback` (for the CLI) and `http://localhost:8000/api/auth/callback` (for the Dashboard) as authorized redirect URLs
6. Run `python main.py --auth`

## ⚙️ Configuration

Edit `config/.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `GROQ_API_KEY` | — | Your Groq API key |
| `POST_SCHEDULE_HOUR` | `9` | Hour to post (24h format) |
| `POST_SCHEDULE_MINUTE` | `0` | Minute to post |
| `POST_AS_ORGANIZATION` | `false` | Post as org page |
| `ENABLE_IMAGE_GENERATION` | `true` | Generate images |
| `PREFERRED_MODEL` | `auto` | LLM model selection |
