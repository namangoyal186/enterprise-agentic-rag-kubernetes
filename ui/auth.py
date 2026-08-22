"""
Google OAuth 2.0 OpenID Connect Authentication Helper for Streamlit.
"""
import os
import threading
import urllib.parse
import requests
import streamlit as st
from dotenv import load_dotenv

# Ensure .env is loaded locally
env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
load_dotenv(dotenv_path=env_path)


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
    """Get the current base URL for redirect."""
    return get_secret("REDIRECT_URI", "http://localhost:8501")


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
    """Sync user profile to backend or database in background thread."""
    def _sync():
        try:
            backend = get_backend_url()
            if backend.startswith("https://"):
                requests.post(
                    f"{backend}/api/users/sync",
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


def exchange_code_for_user(code: str) -> dict | None:
    """Exchange authorization code for tokens and fetch user profile."""
    try:
        token_data = {
            "code": code,
            "client_id": get_google_client_id(),
            "client_secret": get_google_client_secret(),
            "redirect_uri": get_redirect_uri(),
            "grant_type": "authorization_code",
        }
        token_resp = requests.post(GOOGLE_TOKEN_ENDPOINT, data=token_data, timeout=10)
        token_json = token_resp.json()

        access_token = token_json.get("access_token")
        if not access_token:
            print(f"Failed to get access token: {token_json}")
            return None

        headers = {"Authorization": f"Bearer {access_token}"}
        userinfo_resp = requests.get(GOOGLE_USERINFO_ENDPOINT, headers=headers, timeout=10)
        userinfo = userinfo_resp.json()

        user_data = {
            "user_id": userinfo.get("sub"),
            "email": userinfo.get("email"),
            "name": userinfo.get("name", userinfo.get("email", "User")),
            "picture": userinfo.get("picture"),
        }

        # Non-blocking background sync
        sync_user_background(user_data)

        return user_data
    except Exception as e:
        print(f"OAuth Exchange Error: {e}")
        return None


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
    Check query parameters for OAuth callback code or saved session and manage login state.
    """
    # 1. Check in-memory session state first
    if st.session_state.get("user"):
        return st.session_state.user

    query_params = st.query_params

    # 2. Check for persistent session token in URL (preserves login on browser refresh F5)
    if "session" in query_params:
        cached_user = decode_session(query_params["session"])
        if cached_user and "user_id" in cached_user:
            st.session_state.user = cached_user
            return cached_user

    # 3. Check query parameters for Google auth redirect callback (?code=...)
    if "code" in query_params:
        auth_code = query_params["code"]

        # Render loading animation inside matching Kubernetes Enterprise AI card
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.markdown(
                """
                <style>
                [data-testid="stSidebar"], [data-testid="collapsedControl"] {
                    display: none !important;
                }
                .login-card-wrapper {
                    max-width: 520px;
                    margin: 50px auto 0 auto;
                    padding: 38px 34px 28px 34px;
                    background: rgba(255, 255, 255, 0.03);
                    border: 1px solid rgba(255, 255, 255, 0.08);
                    border-radius: 20px;
                    text-align: center;
                    backdrop-filter: blur(16px);
                    box-shadow: 0 12px 40px rgba(0, 0, 0, 0.35);
                }
                .login-title {
                    font-size: 28px;
                    font-weight: 700;
                    color: #ffffff;
                    margin: 0 0 8px 0;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    gap: 10px;
                }
                .login-subtitle {
                    color: #9aa0a6;
                    font-size: 14px;
                    line-height: 1.5;
                    margin-bottom: 22px;
                }
                .feature-tags {
                    display: flex;
                    flex-wrap: wrap;
                    gap: 6px;
                    justify-content: center;
                    margin-bottom: 24px;
                }
                .tag {
                    background: rgba(255, 255, 255, 0.05);
                    color: #cbd5e1;
                    font-size: 11.5px;
                    padding: 4px 10px;
                    border-radius: 8px;
                    border: 1px solid rgba(255, 255, 255, 0.06);
                }
                .google-btn-loading {
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    gap: 12px;
                    width: 100%;
                    max-width: 340px;
                    padding: 12px 28px;
                    background-color: #ffffff;
                    color: #202124;
                    border-radius: 10px;
                    font-size: 15px;
                    font-weight: 600;
                    margin-top: 10px;
                    box-shadow: 0 4px 12px rgba(0,0,0,0.2);
                }
                .spinner-ring {
                    width: 18px;
                    height: 18px;
                    border: 3px solid rgba(0, 0, 0, 0.1);
                    border-top: 3px solid #4285F4;
                    border-right: 3px solid #EA4335;
                    border-bottom: 3px solid #FBBC05;
                    border-left: 3px solid #34A853;
                    border-radius: 50%;
                    animation: spin-ring 0.8s linear infinite;
                }
                @keyframes spin-ring {
                    0% { transform: rotate(0deg); }
                    100% { transform: rotate(360deg); }
                }
                </style>
                <div class="login-card-wrapper">
                    <div class="login-title">☸️ Kubernetes Enterprise AI</div>
                    <div class="login-subtitle">
                        Autonomous Cloud-Native IT Copilot powered by Multi-Agent LangGraph, Qdrant Hybrid RAG, NeMo Guardrails & Qwen 27B.
                    </div>
                    <div class="feature-tags">
                        <span class="tag">⚡ Qwen 27B</span>
                        <span class="tag">🔍 Qdrant Hybrid Vector RAG</span>
                        <span class="tag">🛡️ NeMo Security Guardrails</span>
                        <span class="tag">🐘 Neon PostgreSQL Memory</span>
                        <span class="tag">🚦 Upstash Redis Limiter</span>
                    </div>
                    <div style="display: flex; justify-content: center;">
                        <div class="google-btn-loading">
                            <div class="spinner-ring"></div>
                            <span>Logging In...</span>
                        </div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        user = exchange_code_for_user(auth_code)
        if user:
            st.session_state.user = user
            # Store URL-safe session token so page refresh preserves logged-in state
            st.query_params["session"] = encode_session(user)
            st.rerun()
        else:
            st.error("Failed to complete Google login. Please try again.")
            st.stop()

    return None


def logout_user():
    """Log out current user and completely clear local session state and URL tokens."""
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.query_params.clear()
    st.rerun()
