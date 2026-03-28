"""
LinkedIn OAuth 2.0 Setup Helper

Starts a local HTTP server, opens the LinkedIn consent page in the browser,
captures the authorization code from the callback, and exchanges it for tokens.

Usage: python auth_setup.py
"""

import os
import sys
import webbrowser
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# Add project root to path
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "config", ".env"))


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """Handle the OAuth callback from LinkedIn."""

    auth_code = None
    error = None

    def do_GET(self):
        """Process the callback URL."""
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if "code" in params:
            OAuthCallbackHandler.auth_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"""
            <html>
            <head><style>
                body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                       display: flex; align-items: center; justify-content: center; height: 100vh;
                       margin: 0; background: linear-gradient(135deg, #0a1628, #1a3a6e); color: white; }
                .card { text-align: center; padding: 40px; background: rgba(255,255,255,0.1);
                        border-radius: 16px; backdrop-filter: blur(10px); }
                h1 { color: #00c8ff; font-size: 28px; }
                p { color: #ccc; font-size: 16px; }
            </style></head>
            <body><div class="card">
                <h1>&#10004; Authorization Successful!</h1>
                <p>LinkedIn access token obtained. You can close this tab.</p>
                <p>The auto-poster is now ready to use.</p>
            </div></body></html>
            """)
        elif "error" in params:
            OAuthCallbackHandler.error = params.get("error_description", params["error"])[0]
            self.send_response(400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(f"""
            <html><body style="font-family: sans-serif; text-align: center; padding: 50px;">
                <h1 style="color: red;">Authorization Failed</h1>
                <p>{OAuthCallbackHandler.error}</p>
            </body></html>
            """.encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        """Suppress default HTTP logs."""
        pass


def run_auth_setup():
    """Run the complete OAuth setup flow."""
    from src.linkedin_poster import LinkedInPoster

    # Use user_id 1 for CLI-based setup
    poster = LinkedInPoster(user_id=1)

    if not poster.client_id or not poster.client_secret:
        print("\n❌ LinkedIn credentials not configured!")
        print("   Please set the following in config/.env:")
        print("   - LINKEDIN_CLIENT_ID")
        print("   - LINKEDIN_CLIENT_SECRET")
        print("\n   Get these from: https://developer.linkedin.com/")
        return False

    # Parse port from redirect URI
    from urllib.parse import urlparse
    parsed = urlparse(poster.redirect_uri)
    port = parsed.port or 8080

    print("\n" + "=" * 60)
    print("🔐 LinkedIn OAuth 2.0 Setup")
    print("=" * 60)
    print(f"\n1. Starting local server on port {port}...")

    # Start callback server
    server = HTTPServer(("localhost", port), OAuthCallbackHandler)
    server_thread = threading.Thread(target=server.handle_request)
    server_thread.daemon = True
    server_thread.start()

    # Open browser
    auth_url = poster.get_auth_url()
    print(f"2. Opening LinkedIn authorization page...")
    print(f"   Using Redirect URI: {poster.redirect_uri}")
    print(f"   (Ensure this EXACT URL is registered in your LinkedIn App settings)")
    print(f"   URL: {auth_url[:100]}...")
    webbrowser.open(auth_url)
    print("3. Waiting for authorization...")
    print("   (Authorize in your browser, then come back here)\n")

    # Wait for callback
    server_thread.join(timeout=120)

    if OAuthCallbackHandler.auth_code:
        print("4. Authorization code received! Exchanging for token...")
        try:
            tokens = poster.exchange_code(OAuthCallbackHandler.auth_code)
            print("\n✅ Setup complete!")
            print(f"   Access token expires in: {tokens.get('expires_in', 'N/A')} seconds")
            print(f"   Token saved securely to: config/tokens.json")

            # Test by fetching user info
            try:
                urn = poster.get_user_urn()
                print(f"   Authenticated as: {urn}")
            except Exception:
                pass

            print("\n🚀 You can now run:")
            print("   python main.py --dry-run   (test without posting)")
            print("   python main.py --once       (post one time)")
            print("   python main.py              (start scheduler)")
            return True
        except Exception as e:
            print(f"\n❌ Token exchange failed: {e}")
            return False
    elif OAuthCallbackHandler.error:
        print(f"\n❌ Authorization failed: {OAuthCallbackHandler.error}")
        return False
    else:
        print("\n⏰ Authorization timed out (120 seconds)")
        print("   Please try again: python auth_setup.py")
        return False


if __name__ == "__main__":
    run_auth_setup()
