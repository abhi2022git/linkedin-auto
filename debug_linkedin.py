"""
Debug script to test LinkedIn API directly and diagnose posting issues.
"""
import os
import sys
import json
import requests

sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "config", ".env"))

from src.linkedin_poster import LinkedInPoster

poster = LinkedInPoster()
token = poster._get_access_token()

print("=" * 60)
print("🔍 LinkedIn API Debug")
print("=" * 60)

# 1. Test token introspection
print("\n--- Step 1: Token Check ---")
print(f"Token (first 20 chars): {token[:20]}...")

# 2. Test /v2/userinfo (OpenID Connect)
print("\n--- Step 2: /v2/userinfo ---")
r = requests.get(
    "https://api.linkedin.com/v2/userinfo",
    headers={"Authorization": f"Bearer {token}"}
)
print(f"Status: {r.status_code}")
print(f"Response: {json.dumps(r.json(), indent=2)}")

if r.status_code == 200:
    user_sub = r.json().get("sub")
    user_name = r.json().get("name", "Unknown")
    print(f"\n👤 Authenticated as: {user_name} (sub: {user_sub})")
    author_urn = f"urn:li:person:{user_sub}"
else:
    print("❌ Failed to get user info")
    sys.exit(1)

# 3. Test /v2/me (legacy profile)
print("\n--- Step 3: /v2/me ---")
r2 = requests.get(
    "https://api.linkedin.com/v2/me",
    headers={"Authorization": f"Bearer {token}"}
)
print(f"Status: {r2.status_code}")
if r2.status_code == 200:
    print(f"Response: {json.dumps(r2.json(), indent=2)}")
else:
    print(f"Response: {r2.text[:500]}")

# 4. Try posting with /rest/posts (versioned API)
print("\n--- Step 4: Post via /rest/posts (version 202401) ---")
test_content = "🧪 Testing LinkedIn API integration.\n\nThis is an automated test post to verify posting permissions.\n\n#Test #API"

headers_rest = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json",
    "X-Restli-Protocol-Version": "2.0.0",
    "LinkedIn-Version": "202401",
}

payload_rest = {
    "author": author_urn,
    "commentary": test_content,
    "visibility": "PUBLIC",
    "distribution": {
        "feedDistribution": "MAIN_FEED",
        "targetEntities": [],
        "thirdPartyDistributionChannels": []
    },
    "lifecycleState": "PUBLISHED",
    "isReshareDisabledByAuthor": False
}

r3 = requests.post(
    "https://api.linkedin.com/rest/posts",
    headers=headers_rest,
    json=payload_rest,
)
print(f"Status: {r3.status_code}")
print(f"Headers: {dict(r3.headers)}")
print(f"Body: {r3.text[:1000]}")

if r3.status_code in (200, 201):
    post_id = r3.headers.get("x-restli-id", "")
    print(f"\n✅ /rest/posts succeeded! Post ID: {post_id}")
else:
    print(f"\n❌ /rest/posts failed with {r3.status_code}")

    # 5. Try with legacy /v2/ugcPosts (no version header)
    print("\n--- Step 5: Post via /v2/ugcPosts (legacy, no version header) ---")
    headers_legacy = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    }

    payload_legacy = {
        "author": author_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {
                    "text": test_content
                },
                "shareMediaCategory": "NONE"
            }
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
        }
    }

    r4 = requests.post(
        "https://api.linkedin.com/v2/ugcPosts",
        headers=headers_legacy,
        json=payload_legacy,
    )
    print(f"Status: {r4.status_code}")
    print(f"Headers: {dict(r4.headers)}")
    print(f"Body: {r4.text[:1000]}")

    if r4.status_code == 201:
        post_id = r4.headers.get("X-RestLi-Id", r4.headers.get("x-restli-id", ""))
        print(f"\n✅ /v2/ugcPosts succeeded! Post ID: {post_id}")
    else:
        print(f"\n❌ /v2/ugcPosts also failed with {r4.status_code}")

    # 6. Try with /v2/shares (oldest API)
    print("\n--- Step 6: Post via /v2/shares (oldest API) ---")
    payload_shares = {
        "owner": author_urn,
        "text": {
            "text": test_content
        },
        "distribution": {
            "linkedInDistributionTarget": {}
        }
    }

    r5 = requests.post(
        "https://api.linkedin.com/v2/shares",
        headers=headers_legacy,
        json=payload_shares,
    )
    print(f"Status: {r5.status_code}")
    print(f"Headers: {dict(r5.headers)}")
    print(f"Body: {r5.text[:1000]}")

print("\n" + "=" * 60)
print("Debug complete!")
print("=" * 60)
