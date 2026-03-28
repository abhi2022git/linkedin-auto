"""
Content Scraper: Fetches tech articles from RSS feeds, Medium, and news sources.
"""

import re
import time
import random
import feedparser
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from .utils import Article, load_sources, setup_logging, DatabaseManager

logger = setup_logging()


class ContentScraper:
    """Scrapes tech content from multiple sources."""
    
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    
    def __init__(self, config_path: str = None):
        self.config = load_sources(config_path)
        self.sources = [s for s in self.config["sources"] if s.get("enabled", True)]
        self.keywords = self.config.get("keywords", {})
        self.db = DatabaseManager()
    
    def scrape_all(self, max_age_hours: int = 72) -> List[Article]:
        """Scrape all enabled sources and return ranked articles."""
        all_articles = []
        
        for source in self.sources:
            try:
                articles = self._scrape_source(source, max_age_hours)
                all_articles.extend(articles)
                logger.info(f"  ✓ {source['name']}: {len(articles)} articles")
                time.sleep(random.uniform(0.5, 1.5))  # Rate limiting
            except Exception as e:
                logger.warning(f"  ✗ {source['name']}: {e}")
        
        # Deduplicate
        seen_urls = set()
        unique_articles = []
        for article in all_articles:
            if article.url not in seen_urls and not self.db.is_already_posted(url=article.url, title=article.title):
                seen_urls.add(article.url)
                unique_articles.append(article)
        
        # Score and rank
        scored = self._score_articles(unique_articles)
        scored.sort(key=lambda a: a.relevance_score, reverse=True)
        
        self.db.log_scrape(
            source_count=len(self.sources),
            article_count=len(scored),
            selected_title=scored[0].title if scored else None
        )
        
        logger.info(f"📊 Total: {len(all_articles)} scraped → {len(scored)} unique & unposted")
        return scored
    
    def _scrape_source(self, source: dict, max_age_hours: int) -> List[Article]:
        """Scrape a single source."""
        source_type = source.get("type", "rss")
        
        if source_type == "rss":
            return self._scrape_rss(source, max_age_hours)
        elif source_type == "medium":
            return self._scrape_medium(source, max_age_hours)
        else:
            return self._scrape_rss(source, max_age_hours)
    
    def _scrape_rss(self, source: dict, max_age_hours: int) -> List[Article]:
        """Parse an RSS/Atom feed."""
        articles = []
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        
        try:
            feed = feedparser.parse(source["url"])
        except Exception as e:
            logger.warning(f"Failed to parse {source['url']}: {e}")
            return articles
        
        for entry in feed.entries[:20]:  # Limit per source
            # Parse publish date
            pub_date = None
            for date_field in ("published_parsed", "updated_parsed"):
                parsed = getattr(entry, date_field, None)
                if parsed:
                    try:
                        pub_date = datetime(*parsed[:6], tzinfo=timezone.utc)
                    except Exception:
                        pass
                    break
            
            # Skip old articles
            if pub_date and pub_date < cutoff:
                continue
            
            # Extract summary
            summary = ""
            if hasattr(entry, "summary"):
                summary = BeautifulSoup(entry.summary, "html.parser").get_text(strip=True)
            elif hasattr(entry, "description"):
                summary = BeautifulSoup(entry.description, "html.parser").get_text(strip=True)
            
            # Truncate summary
            if len(summary) > 500:
                summary = summary[:497] + "..."
            
            # Extract tags
            tags = []
            if hasattr(entry, "tags"):
                tags = [t.get("term", "") for t in entry.tags if t.get("term")]
            
            article = Article(
                title=entry.get("title", "Untitled").strip(),
                summary=summary,
                url=entry.get("link", ""),
                source=source["name"],
                published_date=pub_date.isoformat() if pub_date else None,
                tags=tags,
                category=source.get("category", "tech"),
            )
            articles.append(article)
        
        return articles
    
    def _scrape_medium(self, source: dict, max_age_hours: int) -> List[Article]:
        """Scrape Medium RSS feed (Medium exposes public feeds via RSS)."""
        # Medium feeds are actually RSS, so delegate
        return self._scrape_rss(source, max_age_hours)
    
    def _score_articles(self, articles: List[Article]) -> List[Article]:
        """Score articles by relevance using keyword matching."""
        high_kw = [k.lower() for k in self.keywords.get("high_priority", [])]
        med_kw = [k.lower() for k in self.keywords.get("medium_priority", [])]
        
        for article in articles:
            score = 0.0
            text = f"{article.title} {article.summary} {' '.join(article.tags)}".lower()
            
            # High priority keyword matches
            for kw in high_kw:
                if kw in text:
                    score += 3.0
            
            # Medium priority keyword matches
            for kw in med_kw:
                if kw in text:
                    score += 1.5
            
            # Boost for AI/ML category
            if article.category == "ai_ml":
                score += 2.0
            
            # Recency boost
            if article.published_date:
                try:
                    pub = datetime.fromisoformat(article.published_date)
                    hours_old = (datetime.now(timezone.utc) - pub).total_seconds() / 3600
                    if hours_old < 6:
                        score += 3.0
                    elif hours_old < 12:
                        score += 2.0
                    elif hours_old < 24:
                        score += 1.0
                except Exception:
                    pass
            
            # Title quality boost (longer, more descriptive titles)
            word_count = len(article.title.split())
            if 5 <= word_count <= 15:
                score += 1.0
            
            article.relevance_score = score
        
        return articles
    
    def get_best_article(self, max_age_hours: int = 72) -> Optional[Article]:
        """Scrape and return the single best article to post about."""
        logger.info("🔍 Scraping content sources...")
        articles = self.scrape_all(max_age_hours)
        
        if not articles:
            logger.warning("⚠️  No articles found!")
            return None
        
        best = articles[0]
        logger.info(f"🏆 Best topic: \"{best.title}\" (score: {best.relevance_score:.1f})")
        return best
