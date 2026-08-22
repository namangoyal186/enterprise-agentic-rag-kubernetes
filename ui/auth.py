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


def handle_oauth_flow():
    """
    Check query parameters for OAuth callback code and manage login state.
    """
    # 1. Check in-memory session state first
    if st.session_state.get("user"):
        return st.session_state.user

    # 2. Check query parameters for Google auth redirect callback
    query_params = st.query_params
    if "code" in query_params:
        auth_code = query_params["code"]

        # Render loading animation inside card
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.markdown(
                """
                <style>
                [data-testid="stSidebar"], [data-testid="collapsedControl"] {
                    display: none !important;
                }
                .login-card {
                    max-width: 480px;
                    margin: 60px auto;
                    padding: 40px;
                    background: rgba(255, 255, 255, 0.04);
                    border: 1px solid rgba(255, 255, 255, 0.1);
                    border-radius: 16px;
                    text-align: center;
                    backdrop-filter: blur(10px);
                    opacity: 1 !important;
                    filter: none !important;
                }
                .google-btn-loading {
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    gap: 12px;
                    width: 100%;
                    padding: 12px 24px;
                    background-color: #ffffff;
                    color: #3c4043;
                    border-radius: 8px;
                    font-size: 16px;
                    font-weight: 500;
                    margin-top: 20px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.2);
                    opacity: 1 !important;
                    filter: none !important;
                }
                .spinner-ring {
                    width: 20px;
                    height: 20px;
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
                <div class="login-card">
                    <h1 style="margin-bottom: 8px;">🧠 Agent OS</h1>
                    <p style="color: #9aa0a6; font-size: 15px; margin-bottom: 24px;">
                        Enterprise Multi-Agent RAG with Persistent Memory & Guardrails
                    </p>
                    <div class="google-btn-loading">
                        <div class="spinner-ring"></div>
                        <span>Logging In...</span>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        user = exchange_code_for_user(auth_code)
        if user:
            st.session_state.user = user
            st.query_params.clear()
            st.rerun()
        else:
            st.error("Failed to complete Google login. Please try again.")
            st.stop()

    return None


def logout_user():
    """Log out current user and completely clear local session state."""
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.query_params.clear()
    st.rerun()
