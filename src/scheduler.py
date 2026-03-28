"""
Scheduler: APScheduler-based automation for the LinkedIn posting pipeline.
"""

import os
import time
from datetime import datetime
from dotenv import load_dotenv
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from .utils import setup_logging

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", ".env"))

logger = setup_logging()


def _try_log_run_start():
    """Safely start a pipeline run record."""
    try:
        from dashboard.database import log_pipeline_run_start
        return log_pipeline_run_start(platform='linkedin')
    except Exception:
        return None


def _try_log_run_complete(run_id, **kwargs):
    """Safely complete a pipeline run record."""
    if run_id is None:
        return
    try:
        from dashboard.database import log_pipeline_run_complete
        log_pipeline_run_complete(run_id, **kwargs)
    except Exception:
        pass


def run_pipeline(override_model: str = None, user_id: int = 1):
    """Execute one full posting cycle for a specific user."""
    from .scraper import ContentScraper
    from .content_generator import ContentGenerator
    from .image_generator import ImageGenerator
    from .linkedin_poster import LinkedInPoster
    from .utils import DatabaseManager
    from dashboard.database import get_db

    # Fetch user settings
    with get_db() as conn:
        row = conn.execute("SELECT * FROM user_settings WHERE user_id = ?", (user_id,)).fetchone()
        user_settings = dict(row) if row else {}

    logger.info("=" * 60)
    logger.info("🚀 LinkedIn Auto-Poster Pipeline Started")
    logger.info(f"   Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    db = DatabaseManager()
    run_id = _try_log_run_start()
    start_time = time.time()

    try:
        # Step 1: Scrape content
        scraper = ContentScraper()
        article = scraper.get_best_article()
        if not article:
            logger.error("❌ No articles found. Skipping this cycle.")
            _try_log_run_complete(run_id, status='failed', error_message='No articles found',
                                 duration_seconds=round(time.time() - start_time, 2))
            return

        # Step 2: Generate post content
        generator = ContentGenerator(user_id=user_id)
        post_content, model_used = generator.generate_post(article, override_model=override_model)
        logger.info(f"📝 Post generated ({len(post_content)} chars) with {model_used} for user {user_id}")

        # Step 3: Generate image (if enabled)
        image_path = None
        image_generated = 0
        if user_settings.get("enable_image_generation", 1):
            try:
                img_gen = ImageGenerator(user_id=user_id)
                image_path = img_gen.generate(article, post_content=post_content)
                image_generated = 1
            except Exception as e:
                logger.warning(f"⚠️  Image generation failed: {e}, posting without image")

        # Step 4: Post to LinkedIn
        poster = LinkedInPoster(user_id=user_id)
        result = poster.publish(post_content, image_path)

        # Step 5: Record result
        elapsed = round(time.time() - start_time, 2)
        if result.get("success"):
            db.record_post(
                article=article,
                post_content=post_content,
                model_used=model_used,
                linkedin_post_id=result.get("post_id"),
                image_path=image_path
            )
            logger.info(f"🎉 Pipeline completed successfully! Post #{db.get_post_count()}")
            _try_log_run_complete(run_id, status='success',
                                 article_title=article.title, article_source=article.source,
                                 article_url=article.url, model_used=model_used,
                                 post_char_count=len(post_content), image_generated=image_generated,
                                 linkedin_post_id=result.get('post_id'),
                                 duration_seconds=elapsed)
        else:
            logger.error(f"❌ Pipeline failed: {result.get('error', 'Unknown error')}")
            _try_log_run_complete(run_id, status='failed',
                                 article_title=article.title, article_source=article.source,
                                 model_used=model_used, error_message=result.get('error', 'Unknown'),
                                 duration_seconds=elapsed)

    except Exception as e:
        logger.error(f"💥 Pipeline error: {e}", exc_info=True)
        _try_log_run_complete(run_id, status='failed', error_message=str(e),
                             duration_seconds=round(time.time() - start_time, 2))

    logger.info("=" * 60)


def run_dry(verbose: bool = True, override_model: str = None, user_id: int = 1):
    """Run pipeline without posting (dry-run mode)."""
    from .scraper import ContentScraper
    from .content_generator import ContentGenerator
    from .image_generator import ImageGenerator
    from dashboard.database import get_db

    with get_db() as conn:
        row = conn.execute("SELECT enable_image_generation FROM user_settings WHERE user_id = ?", (user_id,)).fetchone()
        enable_image = bool(row["enable_image_generation"]) if row else True

    logger.info(f"🧪 DRY RUN MODE (User {user_id}) — No posts will be published")
    logger.info("=" * 60)

    scraper = ContentScraper()
    article = scraper.get_best_article()
    if not article:
        logger.error("No articles found.")
        return

    generator = ContentGenerator(user_id=user_id)
    post_content = generator.preview_post(article, override_model=override_model)

    if enable_image:
        try:
            img_gen = ImageGenerator(user_id=user_id)
            image_path = img_gen.generate(article, post_content=post_content)
            logger.info(f"🖼️  Image preview: {image_path}")
        except Exception as e:
            logger.warning(f"Image generation failed: {e}")

    logger.info("✅ Dry run complete. Review the output above.")


def start_scheduler():
    """Start the APScheduler for automated posting across all users."""
    from dashboard.database import get_db
    scheduler = BlockingScheduler()

    with get_db() as conn:
        # Get all users who have configured settings
        users = conn.execute("SELECT user_id, post_schedule_hour, post_schedule_minute FROM user_settings").fetchall()

    if not users:
        logger.warning("No users found in database. Scheduler will have no jobs.")

    for u in users:
        uid = u["user_id"]
        h = u["post_schedule_hour"] or 9
        m = u["post_schedule_minute"] or 0

        scheduler.add_job(
            run_pipeline,
            kwargs={"user_id": uid},
            trigger=CronTrigger(hour=h, minute=m),
            id=f"linkedin_auto_post_{uid}",
            name=f"LinkedIn Auto-Post User {uid}",
            misfire_grace_time=3600,
        )
        logger.info(f"⏰ Scheduled User {uid} for {h:02d}:{m:02d}")

    logger.info(f"🚀 Multi-tenant Scheduler started with {len(users)} jobs.")
    logger.info("   Press Ctrl+C to stop")
    
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("👋 Scheduler stopped")
        scheduler.shutdown()
