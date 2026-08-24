import os
import datetime
import threading
import urllib.parse
import requests
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

# Ensure .env is loaded locally
env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
load_dotenv(dotenv_path=env_path)


def get_cookie_manager():
    """Retrieve CookieManager instance stored safely in session state."""
    try:
        import extra_streamlit_components as stx
        if "cookie_manager" not in st.session_state:
            st.session_state.cookie_manager = stx.CookieManager(key="kube_auth_cookie_mgr")
        return st.session_state.cookie_manager
    except Exception:
        return None


def get_secret(key: str, default: str = "") -> str:
    """Retrieve secret from Streamlit Cloud st.secrets or os.environ."""
    try:
        if hasattr(st, "secrets") and key in st.secrets:
            return str(st.secrets[key])
    except Exception:
        pass
    return os.getenv(key, default)


# Standard Google OAuth Endpoints
GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_ENDPOINT = "https://www.googleapis.com/oauth2/v3/userinfo"


def get_google_client_id() -> str:
    return get_secret("GOOGLE_CLIENT_ID", "")


def get_google_client_secret() -> str:
    return get_secret("GOOGLE_CLIENT_SECRET", "")


GOOGLE_CLIENT_ID = get_google_client_id()
GOOGLE_CLIENT_SECRET = get_google_client_secret()


def get_backend_url() -> str:
    return get_secret("BACKEND_URL", "http://localhost:8000")


def get_redirect_uri() -> str:
    """Get the current base URL for redirect, strictly normalized."""
    render_url = os.getenv("RENDER_EXTERNAL_URL")
    if render_url:
        return render_url.strip().rstrip("/")
    return get_secret("REDIRECT_URI", "http://localhost:8501").strip().rstrip("/")


def get_google_auth_url() -> str:
    """Construct Google OAuth 2.0 authorization URL."""
    params = {
        "client_id": get_google_client_id(),
        "redirect_uri": get_redirect_uri(),
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "select_account",
    }
    return f"{GOOGLE_AUTH_ENDPOINT}?{urllib.parse.urlencode(params)}"


def sync_user_background(user_data: dict):
    """Fire and forget async sync of user profile to Neon database."""
    def _sync():
        try:
            backend_url = get_backend_url()
            if backend_url.startswith("https://"):
                requests.post(
                    f"{backend_url}/api/users/sync",
                    json={
                        "user_id": user_data["user_id"],
                        "email": user_data["email"],
                        "name": user_data["name"],
                        "picture_url": user_data["picture"],
                    },
                    timeout=10,
                )
            else:
                from app.db.database import sync_user_profile
                sync_user_profile(
                    user_id=user_data["user_id"],
                    email=user_data["email"],
                    name=user_data["name"],
                    picture_url=user_data["picture"],
                )
        except Exception as e:
            print(f"Background user sync notice: {e}")

    threading.Thread(target=_sync, daemon=True).start()


def exchange_code_for_user(code: str) -> tuple[dict | None, str | None]:
    """Exchange authorization code for tokens and fetch user profile with detailed diagnostics."""
    try:
        redirect_uri = get_redirect_uri()
        token_data = {
            "code": code,
            "client_id": get_google_client_id(),
            "client_secret": get_google_client_secret(),
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        token_resp = requests.post(GOOGLE_TOKEN_ENDPOINT, data=token_data, timeout=12)
        token_json = token_resp.json()

        access_token = token_json.get("access_token")
        if not access_token:
            err_desc = token_json.get("error_description") or token_json.get("error") or str(token_json)
            print(f"Failed to get access token: {token_json}")
            return None, f"{err_desc} (Redirect URI: {redirect_uri})"

        headers = {"Authorization": f"Bearer {access_token}"}
        userinfo_resp = requests.get(GOOGLE_USERINFO_ENDPOINT, headers=headers, timeout=12)
        userinfo = userinfo_resp.json()

        user_data = {
            "user_id": userinfo.get("sub"),
            "email": userinfo.get("email"),
            "name": userinfo.get("name", userinfo.get("email", "User")),
            "picture": userinfo.get("picture"),
        }

        # Non-blocking background sync
        sync_user_background(user_data)

        return user_data, None
    except Exception as e:
        print(f"OAuth Exchange Error: {e}")
        return None, str(e)


import base64
import json


def encode_session(user_data: dict) -> str:
    """Encode user data into a clean URL-safe session token."""
    try:
        raw_bytes = json.dumps(user_data).encode("utf-8")
        return base64.urlsafe_b64encode(raw_bytes).decode("utf-8")
    except Exception:
        return ""


def decode_session(token: str) -> dict | None:
    """Decode session token back into user data."""
    try:
        raw_bytes = base64.urlsafe_b64decode(token.encode("utf-8"))
        return json.loads(raw_bytes.decode("utf-8"))
    except Exception:
        return None


def handle_oauth_flow():
    """
    Check query parameters, cookies, or OAuth callback code and manage persistent login.
    """
    # 1. Check in-memory session state first
    if st.session_state.get("user"):
        return st.session_state.user

    query_params = st.query_params
    cookie_mgr = get_cookie_manager()

    # 2. Check browser cookie for cross-tab persistence
    if cookie_mgr:
        try:
            cookie_session = cookie_mgr.get(cookie="kube_rag_session")
            if cookie_session:
                cached_user = decode_session(cookie_session)
                if cached_user and "user_id" in cached_user:
                    st.session_state.user = cached_user
                    st.query_params["session"] = cookie_session
                    return cached_user
        except Exception:
            pass

    # 3. Check for persistent session token in URL (preserves login on browser refresh F5)
    if "session" in query_params:
        session_str = query_params["session"]
        cached_user = decode_session(session_str)
        if cached_user and "user_id" in cached_user:
            st.session_state.user = cached_user
            if cookie_mgr:
                try:
                    expires = datetime.datetime.now() + datetime.timedelta(days=30)
                    cookie_mgr.set("kube_rag_session", session_str, expires_at=expires)
                except Exception:
                    pass
            return cached_user

    # 4. Check query parameters for Google auth redirect callback (?code=...)
    if "code" in query_params:
        auth_code = query_params["code"]
        user, err_msg = exchange_code_for_user(auth_code)
        if user:
            st.session_state.user = user
            encoded = encode_session(user)
            st.query_params.clear()
            st.query_params["session"] = encoded
            if cookie_mgr:
                try:
                    expires = datetime.datetime.now() + datetime.timedelta(days=30)
                    cookie_mgr.set("kube_rag_session", encoded, expires_at=expires)
                except Exception:
                    pass
            st.rerun()
        else:
            st.query_params.clear()
            st.error(f"❌ Google Login Error: {err_msg}")
            if st.button("🔄 Try Again", type="primary", use_container_width=True):
                st.rerun()
            st.stop()

    return None


def logout_user():
    """Log out current user and completely clear local session state, cookies, and query params."""
    cookie_mgr = get_cookie_manager()
    if cookie_mgr:
        try:
            cookie_mgr.delete("kube_rag_session")
        except Exception:
            pass
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.query_params.clear()
    st.rerun()
