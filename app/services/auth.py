import base64
import hashlib
import hmac
import json
import os
import threading
import time
import urllib.parse
from typing import Optional

import requests

from app.config import settings

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_ENDPOINT = "https://www.googleapis.com/oauth2/v3/userinfo"

SESSION_SECRET_KEY = (
    settings.API_KEY
    or os.getenv("SESSION_SECRET")
    or "enterprise-agentic-rag-session-secret-key-2026"
).encode("utf-8")

SESSION_COOKIE_NAME = "kube_session"


def get_redirect_uri(request_host_url: str = "") -> str:
    """
    Constructs the absolute redirect URI for Google OAuth callback.
    Prioritizes RENDER_EXTERNAL_URL in production, falls back to REDIRECT_URI or request_host_url.
    """
    render_url = os.getenv("RENDER_EXTERNAL_URL")
    if render_url:
        return f"{render_url.strip().rstrip('/')}/auth/callback"

    env_redirect = os.getenv("REDIRECT_URI")
    if env_redirect:
        base = env_redirect.strip().rstrip("/")
        if not base.endswith("/auth/callback"):
            return f"{base}/auth/callback"
        return base

    if request_host_url:
        return f"{request_host_url.strip().rstrip('/')}/auth/callback"

    return "http://localhost:8000/auth/callback"


def get_google_auth_url(redirect_uri: str) -> str:
    """Generates the Google OAuth 2.0 authorization URL."""
    client_id = settings.GOOGLE_CLIENT_ID or os.getenv("GOOGLE_CLIENT_ID", "")
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "select_account",
    }
    return f"{GOOGLE_AUTH_ENDPOINT}?{urllib.parse.urlencode(params)}"


def exchange_code_for_user(code: str, redirect_uri: str) -> tuple[Optional[dict], Optional[str]]:
    """
    Exchanges the OAuth authorization code for Google tokens and fetches the user profile.
    Tries primary redirect_uri and fallback variants to match Google Cloud Console URI settings.
    """
    client_id = settings.GOOGLE_CLIENT_ID or os.getenv("GOOGLE_CLIENT_ID", "")
    client_secret = settings.GOOGLE_CLIENT_SECRET or os.getenv("GOOGLE_CLIENT_SECRET", "")

    if not client_id or not client_secret:
        return None, "GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET is missing."

    candidates = [redirect_uri]
    if "/auth/callback" in redirect_uri:
        candidates.append(redirect_uri.replace("/auth/callback", ""))
        candidates.append(redirect_uri.replace("/auth/callback", "/"))
    elif not redirect_uri.endswith("/auth/callback"):
        candidates.append(f"{redirect_uri.rstrip('/')}/auth/callback")

    last_error = "Unknown exchange error"
    for uri in candidates:
        try:
            token_data = {
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": uri,
                "grant_type": "authorization_code",
            }
            token_resp = requests.post(GOOGLE_TOKEN_ENDPOINT, data=token_data, timeout=8)
            token_json = token_resp.json()

            access_token = token_json.get("access_token")
            if not access_token:
                last_error = token_json.get("error_description") or token_json.get("error") or str(token_json)
                continue

            headers = {"Authorization": f"Bearer {access_token}"}
            userinfo_resp = requests.get(GOOGLE_USERINFO_ENDPOINT, headers=headers, timeout=8)
            userinfo = userinfo_resp.json()

            user_data = {
                "user_id": userinfo.get("sub"),
                "email": userinfo.get("email", ""),
                "name": userinfo.get("name", userinfo.get("email", "User")),
                "picture": userinfo.get("picture", ""),
                "auth_time": int(time.time()),
            }

            # Asynchronously sync profile to Neon database
            sync_user_profile_bg(user_data)

            return user_data, None
        except Exception as e:
            last_error = str(e)

    return None, f"OAuth Token Error: {last_error}"



def sync_user_profile_bg(user_data: dict):
    """Background fire-and-forget sync to Neon PostgreSQL."""
    def _sync():
        try:
            from app.db.database import sync_user_profile
            sync_user_profile(
                user_id=user_data["user_id"],
                email=user_data["email"],
                name=user_data["name"],
                picture_url=user_data.get("picture", ""),
            )
        except Exception as e:
            print(f"[Auth] Background user sync notice: {e}")

    threading.Thread(target=_sync, daemon=True).start()


def create_session_token(user_data: dict) -> str:
    """Creates a tamper-proof HMAC-SHA256 signed session token."""
    raw_payload = json.dumps(user_data, separators=(",", ":")).encode("utf-8")
    b64_payload = base64.urlsafe_b64encode(raw_payload).decode("utf-8").rstrip("=")
    signature = hmac.new(SESSION_SECRET_KEY, b64_payload.encode("utf-8"), hashlib.sha256).digest()
    b64_sig = base64.urlsafe_b64encode(signature).decode("utf-8").rstrip("=")
    return f"{b64_payload}.{b64_sig}"


def verify_session_token(token: str) -> Optional[dict]:
    """Verifies HMAC-SHA256 signature and decodes user session data."""
    if not token or "." not in token:
        return None
    try:
        b64_payload, b64_sig = token.split(".", 1)

        # Verify signature
        expected_sig = hmac.new(SESSION_SECRET_KEY, b64_payload.encode("utf-8"), hashlib.sha256).digest()
        expected_b64_sig = base64.urlsafe_b64encode(expected_sig).decode("utf-8").rstrip("=")

        if not hmac.compare_digest(b64_sig, expected_b64_sig):
            return None

        # Add base64 padding if needed
        padding = 4 - (len(b64_payload) % 4)
        if padding != 4:
            b64_payload += "=" * padding

        raw_payload = base64.urlsafe_b64decode(b64_payload.encode("utf-8"))
        user_data = json.loads(raw_payload.decode("utf-8"))
        return user_data
    except Exception:
        return None
