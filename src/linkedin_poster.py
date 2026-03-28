"""
LinkedIn Poster: Handles OAuth 2.0 authentication and posting to LinkedIn API.
"""

import os
import json
import time
import requests
from typing import Optional
from datetime import datetime, timezone
from dotenv import load_dotenv
from cryptography.fernet import Fernet
from .utils import Article, setup_logging, get_project_root

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", ".env"))

logger = setup_logging()


# ── Token Storage ────────────────────────────────────────────────────────────

class TokenManager:
    """Encrypts and manages LinkedIn OAuth tokens in the database."""

    def __init__(self, user_id: int):
        self.user_id = user_id
        self.key_file = os.path.join(get_project_root(), "config", ".token_key")
        os.makedirs(os.path.dirname(self.key_file), exist_ok=True)
        self._ensure_key()

    def _ensure_key(self):
        """Generate or load encryption key."""
        if os.path.exists(self.key_file):
            with open(self.key_file, "rb") as f:
                self.key = f.read()
        else:
            self.key = Fernet.generate_key()
            with open(self.key_file, "wb") as f:
                f.write(self.key)
        self.cipher = Fernet(self.key)

    def save_tokens(self, tokens: dict):
        """Encrypt and save tokens to the user_settings database."""
        data = json.dumps(tokens).encode()
        encrypted = self.cipher.encrypt(data).decode('utf-8')
        
        # We need to import get_db lazily to avoid circular imports if any
        import sqlite3
        db_path = os.path.join(get_project_root(), "data", "history.db")
        with sqlite3.connect(db_path) as conn:
            conn.execute("UPDATE user_settings SET linkedin_access_token = ? WHERE user_id = ?", (encrypted, self.user_id))
            conn.commit()
        logger.info(f"🔐 Tokens saved securely for user_id={self.user_id}")

    def load_tokens(self) -> Optional[dict]:
        """Load and decrypt tokens from the database."""
        import sqlite3
        db_path = os.path.join(get_project_root(), "data", "history.db")
        with sqlite3.connect(db_path) as conn:
            row = conn.execute("SELECT linkedin_access_token FROM user_settings WHERE user_id = ?", (self.user_id,)).fetchone()
            
        if not row or not row[0]:
            return None
            
        try:
            encrypted_str = row[0]
            data = self.cipher.decrypt(encrypted_str.encode('utf-8'))
            return json.loads(data.decode('utf-8'))
        except Exception as e:
            logger.error(f"Failed to load tokens for user {self.user_id}: {e}")
            return None

    def has_tokens(self) -> bool:
        """Check if tokens exist in the db for this user."""
        return self.load_tokens() is not None


# ── LinkedIn API Client ─────────────────────────────────────────────────────

class LinkedInPoster:
    """Posts content to LinkedIn using the REST API."""

    API_BASE = "https://api.linkedin.com"
    AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
    TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"

    def __init__(self, user_id: int):
        self.user_id = user_id
        
        # Load user settings from SQLite instead of .env
        import sqlite3
        db_path = os.path.join(get_project_root(), "data", "history.db")
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM user_settings WHERE user_id = ?", (self.user_id,)).fetchone()
            settings = dict(row) if row else {}
            
        self.client_id = settings.get("linkedin_client_id") or os.getenv("LINKEDIN_CLIENT_ID")
        self.client_secret = settings.get("linkedin_client_secret") or os.getenv("LINKEDIN_CLIENT_SECRET")
        self.post_as_org = False  # Placeholder logic
        self.org_id = ""
        
        self.dashboard_redirect_uri = os.getenv("LINKEDIN_DASHBOARD_REDIRECT_URI", "http://localhost:8000/api/auth/callback")
        self.cli_redirect_uri = os.getenv("LINKEDIN_REDIRECT_URI", "http://localhost:8080/callback")
        
        # Default to CLI URI if not context is provided
        self.redirect_uri = self.cli_redirect_uri
        self.token_mgr = TokenManager(user_id=self.user_id)

        if not self.client_id or not self.client_secret:
            logger.warning(
                f"⚠️  LinkedIn credentials not configured for user {self.user_id}! "
                "Update them in the SaaS dashboard Settings tab."
            )

    def get_auth_url(self) -> str:
        """Generate the OAuth authorization URL."""
        scopes = "openid profile w_member_social"
        if self.post_as_org:
            scopes += " w_organization_social"

        return (
            f"{self.AUTH_URL}?"
            f"response_type=code&"
            f"client_id={self.client_id}&"
            f"redirect_uri={self.redirect_uri}&"
            f"scope={scopes}&"
            f"state=linkedin_auto_poster"
        )

    def exchange_code(self, auth_code: str) -> dict:
        """Exchange authorization code for access token."""
        response = requests.post(
            self.TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": auth_code,
                "redirect_uri": self.redirect_uri,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        tokens = response.json()

        # Add metadata
        tokens["obtained_at"] = datetime.now(timezone.utc).isoformat()

        self.token_mgr.save_tokens(tokens)
        logger.info("✅ Access token obtained successfully!")
        return tokens

    def _get_access_token(self) -> str:
        """Get the current access token."""
        tokens = self.token_mgr.load_tokens()
        if not tokens:
            raise RuntimeError(
                "No LinkedIn tokens found! Run 'python main.py --auth' first."
            )

        # Check if token might be expired (LinkedIn tokens last 60 days)
        obtained = tokens.get("obtained_at", "")
        if obtained:
            try:
                obtained_dt = datetime.fromisoformat(obtained)
                expires_in = tokens.get("expires_in", 5184000)  # Default 60 days
                elapsed = (datetime.now(timezone.utc) - obtained_dt).total_seconds()
                if elapsed > expires_in - 86400:  # Refresh 1 day before expiry
                    logger.warning("⚠️  Token is near expiry. You may need to re-authenticate.")
                    logger.warning("   Run: python main.py --auth")
            except Exception:
                pass

        return tokens["access_token"]

    def _get_headers(self) -> dict:
        """Get API request headers."""
        return {
            "Authorization": f"Bearer {self._get_access_token()}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
            "LinkedIn-Version": "202603",
        }

    def get_user_urn(self) -> str:
        """Get the authenticated user's URN."""
        response = requests.get(
            f"{self.API_BASE}/v2/userinfo",
            headers=self._get_headers(),
        )
        response.raise_for_status()
        user_info = response.json()
        user_id = user_info.get("sub")
        return f"urn:li:person:{user_id}"

    def _get_owner_urn(self) -> str:
        """Get the owner URN (person or organization)."""
        if self.post_as_org and self.org_id:
            return f"urn:li:organization:{self.org_id}"
        return self.get_user_urn()

    def post_text(self, content: str) -> dict:
        """Publish a text-only post to LinkedIn using /rest/posts (primary)."""
        owner = self._get_owner_urn()
        logger.info(f"📤 Posting to LinkedIn as {owner}...")

        payload = {
            "author": owner,
            "commentary": content,
            "visibility": "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": []
            },
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False
        }

        response = requests.post(
            f"{self.API_BASE}/rest/posts",
            headers=self._get_headers(),
            json=payload,
        )

        logger.info(f"📋 Response status: {response.status_code}")
        logger.info(f"📋 Response headers: {dict(response.headers)}")
        logger.info(f"📋 Response body: {response.text[:500]}")

        if response.status_code in (200, 201):
            post_id = response.headers.get("x-restli-id", response.headers.get("X-RestLi-Id", ""))
            logger.info(f"✅ Post published! ID: {post_id}")
            return {"success": True, "post_id": post_id}
        else:
            error_detail = response.text
            logger.error(f"❌ /rest/posts failed: {response.status_code} — {error_detail}")
            
            # Fallback to legacy /v2/ugcPosts endpoint
            return self._post_text_legacy(content, owner)

    def _post_text_legacy(self, content: str, owner: str) -> dict:
        """Fallback: Post using the legacy /v2/ugcPosts endpoint."""
        logger.info("🔄 Trying legacy /v2/ugcPosts endpoint...")

        # Legacy endpoint doesn't use LinkedIn-Version header
        headers = {
            "Authorization": f"Bearer {self._get_access_token()}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        }

        payload = {
            "author": owner,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {
                        "text": content
                    },
                    "shareMediaCategory": "NONE"
                }
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
            }
        }

        response = requests.post(
            f"{self.API_BASE}/v2/ugcPosts",
            headers=headers,
            json=payload,
        )

        logger.info(f"📋 Legacy response: {response.status_code} — {response.text[:500]}")

        if response.status_code == 201:
            post_id = response.headers.get("X-RestLi-Id", response.headers.get("x-restli-id", ""))
            logger.info(f"✅ Post published via legacy endpoint! ID: {post_id}")
            return {"success": True, "post_id": post_id}
        else:
            logger.error(f"❌ Both endpoints failed: {response.status_code} — {response.text}")
            return {"success": False, "error": response.text}

    def post_with_image(self, content: str, image_path: str) -> dict:
        """Publish a post with an image to LinkedIn."""
        owner = self._get_owner_urn()
        logger.info(f"📤 Posting with image to LinkedIn as {owner}...")

        # Step 1: Initialize image upload
        init_payload = {
            "initializeUploadRequest": {
                "owner": owner
            }
        }

        init_response = requests.post(
            f"{self.API_BASE}/rest/images?action=initializeUpload",
            headers=self._get_headers(),
            json=init_payload,
        )

        if init_response.status_code != 200:
            logger.warning(f"Image upload init failed: {init_response.text}")
            logger.info("Falling back to text-only post...")
            return self.post_text(content)

        upload_info = init_response.json().get("value", {})
        upload_url = upload_info.get("uploadUrl")
        image_urn = upload_info.get("image")

        if not upload_url or not image_urn:
            logger.warning("Missing upload URL or image URN, falling back to text-only")
            return self.post_text(content)

        # Step 2: Upload the image binary
        with open(image_path, "rb") as img_file:
            upload_headers = {
                "Authorization": f"Bearer {self._get_access_token()}",
                "Content-Type": "application/octet-stream",
            }
            upload_response = requests.put(
                upload_url,
                headers=upload_headers,
                data=img_file.read(),
            )

        if upload_response.status_code not in (200, 201):
            logger.warning(f"Image upload failed: {upload_response.text}")
            logger.info("Falling back to text-only post...")
            return self.post_text(content)

        logger.info("📸 Image uploaded successfully")

        # Step 3: Create the post with the image
        post_payload = {
            "author": owner,
            "commentary": content,
            "visibility": "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": []
            },
            "content": {
                "media": {
                    "title": "Post Image",
                    "id": image_urn
                }
            },
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False
        }

        response = requests.post(
            f"{self.API_BASE}/rest/posts",
            headers=self._get_headers(),
            json=post_payload,
        )

        if response.status_code in (200, 201):
            post_id = response.headers.get("x-restli-id", "")
            logger.info(f"✅ Post with image published! ID: {post_id}")
            return {"success": True, "post_id": post_id}
        else:
            logger.error(f"❌ Image post failed: {response.status_code} — {response.text}")
            logger.info("Falling back to text-only post...")
            return self.post_text(content)

    def publish(self, content: str, image_path: str = None) -> dict:
        """Publish a post (with or without image)."""
        if image_path and os.path.exists(image_path):
            return self.post_with_image(content, image_path)
        return self.post_text(content)
