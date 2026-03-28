"""
LinkedIn Auto-Poster — Main Entry Point

Usage:
    python main.py              Start the scheduler (posts daily)
    python main.py --once       Run one posting cycle
    python main.py --dry-run    Generate content without posting
    python main.py --auth       Set up LinkedIn OAuth credentials
    python main.py --status     Show posting stats
"""

import sys
import os
import argparse

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "config", ".env"))


def show_banner():
    """Display the application banner."""
    banner = """
    ╔══════════════════════════════════════════════════════╗
    ║                                                      ║
    ║   🤖 LinkedIn Auto-Poster                            ║
    ║   ─────────────────────────                          ║
    ║   Scrape → Generate → Post — Fully Automated        ║
    ║                                                      ║
    ║   Powered by Groq (Llama 3, Mixtral, Gemma)         ║
    ║                                                      ║
    ╚══════════════════════════════════════════════════════╝
    """
    print(banner)


def show_status():
    """Show posting statistics."""
    from src.utils import DatabaseManager
    db = DatabaseManager()

    count = db.get_post_count()
    last_model = db.get_last_model_used()

    print(f"\n📊 Posting Statistics")
    print(f"   Total posts: {count}")
    print(f"   Last model used: {last_model or 'N/A'}")

    # Check token status
    from src.linkedin_poster import TokenManager
    tm = TokenManager(user_id=1)
    if tm.has_tokens():
        print(f"   LinkedIn auth: ✅ Configured")
    else:
        print(f"   LinkedIn auth: ❌ Not configured (run --auth)")

    # Check Groq key
    if os.getenv("GROQ_API_KEY"):
        print(f"   Groq API key: ✅ Set")
    else:
        print(f"   Groq API key: ❌ Not set")

    print()


def main():
    parser = argparse.ArgumentParser(
        description="LinkedIn Auto-Poster — Automated tech content posting",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --auth       Set up LinkedIn OAuth (do this first!)
  python main.py --dry-run    Test the pipeline without posting
  python main.py --once       Post once and exit
  python main.py              Start the daily scheduler
        """,
    )
    parser.add_argument("--auth", action="store_true", help="Run LinkedIn OAuth setup")
    parser.add_argument("--once", action="store_true", help="Run one posting cycle and exit")
    parser.add_argument("--dry-run", action="store_true", help="Generate content without posting")
    parser.add_argument("--status", action="store_true", help="Show posting statistics")

    args = parser.parse_args()
    show_banner()

    if args.auth:
        from auth_setup import run_auth_setup
        run_auth_setup()

    elif args.dry_run:
        from src.scheduler import run_dry
        run_dry()

    elif args.once:
        from src.scheduler import run_pipeline
        run_pipeline()

    elif args.status:
        show_status()

    else:
        # Start scheduler
        from src.scheduler import start_scheduler
        show_status()
        start_scheduler()


if __name__ == "__main__":
    main()
