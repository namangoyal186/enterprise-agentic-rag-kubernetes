import os
import re
import sys
import time
import uuid

# Ensure root and ui directory are in Python path
_current_dir = os.path.dirname(os.path.abspath(__file__))
_root_dir = os.path.abspath(os.path.join(_current_dir, ".."))
if _root_dir not in sys.path:
    sys.path.insert(0, _root_dir)
if _current_dir not in sys.path:
    sys.path.insert(0, _current_dir)

import logfire
import requests
import streamlit as st
from dotenv import load_dotenv

# Load local .env
env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
load_dotenv(dotenv_path=env_path)

# Recursively synchronize all Streamlit Cloud st.secrets into os.environ
def _sync_secrets(secrets_dict):
    for k, v in secrets_dict.items():
        if isinstance(v, dict):
            _sync_secrets(v)
        elif isinstance(v, (str, int, float, bool)):
            os.environ[str(k)] = str(v)

try:
    if hasattr(st, "secrets"):
        _sync_secrets(dict(st.secrets))
except Exception:
    pass

try:
    from auth import (
        get_google_auth_url,
        handle_oauth_flow,
        logout_user,
    )
except (ImportError, KeyError):
    from ui.auth import (
        get_google_auth_url,
        handle_oauth_flow,
        logout_user,
    )

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")


def get_inprocess_client():
    """Retrieve FastAPI TestClient with verified startup."""
    from fastapi.testclient import TestClient
    from app.main import app, startup_event
    if getattr(app.state, "rag_agent", None) is None:
        startup_event()
    return TestClient(app)


def api_request(method: str, path: str, json_data: dict = None, headers: dict = None, timeout: int = 180):
    """
    Unified API dispatcher:
    - If BACKEND_URL starts with 'https://', sends standard network HTTP request.
    - Otherwise, routes directly in-process to the FastAPI agent app.
    """
    if BACKEND_URL.startswith("https://"):
        url = f"{BACKEND_URL}{path}"
        if method.upper() == "GET":
            return requests.get(url, headers=headers, timeout=timeout)
        elif method.upper() == "POST":
            return requests.post(url, json=json_data, headers=headers, timeout=timeout)
        elif method.upper() == "DELETE":
            return requests.delete(url, headers=headers, timeout=timeout)

    client = get_inprocess_client()
    if method.upper() == "GET":
        return client.get(path, headers=headers)
    elif method.upper() == "POST":
        return client.post(path, json=json_data, headers=headers)
    elif method.upper() == "DELETE":
        return client.delete(path, headers=headers)


def clean_think_tags(text: str) -> str:
    """Strips internal <think>...</think> reasoning traces from reasoning models."""
    if not isinstance(text, str):
        return str(text)
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    return cleaned if cleaned else text


# Initialize Logfire
LOGFIRE_STATUS = "Unknown"
try:
    token = os.getenv("LOGFIRE_TOKEN")
    base_url = os.getenv("LOGFIRE_BASE_URL")
    if not base_url and token and token.startswith("pylf_v2_eu_"):
        base_url = "https://logfire-eu.pydantic.dev"
    if not token:
        LOGFIRE_STATUS = "Standby (LOGFIRE_TOKEN not set)"
    else:
        logfire.configure(
            token=token,
            advanced=logfire.AdvancedOptions(base_url=base_url) if base_url else None,
        )
        LOGFIRE_STATUS = "Connected & Tracing"
except Exception as e:
    LOGFIRE_STATUS = f"Standby ({e})"


# Check authentication state upfront
is_authenticated = bool(st.session_state.get("user"))

# --- PAGE CONFIG ---
st.set_page_config(
    page_title="Kubernetes Enterprise AI",
    page_icon="☸️",
    layout="wide",
    initial_sidebar_state="expanded" if is_authenticated else "collapsed",
)

# Custom CSS for polished responsive alignment, mobile viewport support, and clean sidebar toggle
hide_sidebar_css = "[data-testid=\"stSidebar\"], [data-testid=\"collapsedControl\"] { display: none !important; }" if not is_authenticated else ""

st.markdown(
    f"""
    <style>
    /* Hide Deploy button, Streamlit developer menu, footer, and floating badges */
    .stDeployButton,
    [data-testid="stToolbar"],
    div[data-testid="stStatusWidget"],
    .viewerBadge_container__1QSob,
    .viewerBadge_link__1S137,
    [data-testid="manage-app-button"],
    div[class*="viewerBadge"],
    div[class*="ProfileButton"],
    div[class*="StatusWidget"],
    div[class*="FloatingActionButton"],
    div[class*="hostedWithStreamlit"],
    div[class*="createdBy"],
    div[class*="streamlit-badge"],
    div[class*="stAppDeployButton"],
    div[class*="BottomBlock"],
    a[href*="streamlit.app"],
    a[href*="share.streamlit.io"],
    a[href*="streamlit.io"],
    #MainMenu,
    footer {{
        display: none !important;
        visibility: hidden !important;
        opacity: 0 !important;
        height: 0px !important;
        width: 0px !important;
        pointer-events: none !important;
        position: absolute !important;
        left: -9999px !important;
    }}
    
    /* Make header transparent so the sidebar toggle arrow is always accessible on mobile/desktop */
    header[data-testid="stHeader"] {{
        background: transparent !important;
    }}

    /* Prevent Streamlit grey-out overlay and dimming during script execution */
    div[data-testid="stAppViewContainer"] > section {{
        opacity: 1 !important;
        filter: none !important;
    }}
    .element-container, .stMarkdown, .login-card, .google-btn-loading {{
        opacity: 1 !important;
        filter: none !important;
    }}
    div[data-testid="stMarkdownContainer"] {{
        opacity: 1 !important;
        filter: none !important;
    }}

    /* Hide sidebar completely if not logged in */
    {hide_sidebar_css}

    /* Center align column contents in the sidebar */
    [data-testid="stSidebar"] div[data-testid="stHorizontalBlock"] {{
        align-items: center !important;
        gap: 6px !important;
    }}
    /* Style thread delete button */
    [data-testid="stSidebar"] button[kind="secondary"] {{
        text-align: left;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }}
    .thread-del-btn button {{
        padding: 4px 8px !important;
        min-height: 38px !important;
        margin: 0 !important;
    }}

    /* Responsive Mobile & Tablet Layout Adjustments */
    @media (max-width: 768px) {{
        .main .block-container {{
            padding-left: 1rem !important;
            padding-right: 1rem !important;
            padding-top: 2.5rem !important;
            max-width: 100% !important;
        }}
        [data-testid="stSidebar"] {{
            min-width: 280px !important;
            max-width: 85vw !important;
        }}
        .login-card-wrapper {{
            padding: 28px 18px !important;
            margin: 20px auto 0 auto !important;
        }}
    }}
    </style>
    """,
    unsafe_allow_html=True,
)

# --- AVATARS ---
AI_AVATAR = "🤖"
USER_AVATAR = "👤"


# --- AUTHENTICATION FLOW ---
current_user = handle_oauth_flow()


# ==============================================================================
# 1. LOGIN SCREEN (If not authenticated)
# ==============================================================================
if not current_user:
    st.markdown(
        """
        <style>
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
        .kube-badge {
            display: inline-block;
            background: rgba(50, 108, 229, 0.15);
            color: #60a5fa;
            border: 1px solid rgba(96, 165, 250, 0.3);
            font-size: 11px;
            font-weight: 600;
            letter-spacing: 0.8px;
            padding: 4px 12px;
            border-radius: 20px;
            margin-bottom: 14px;
            text-transform: uppercase;
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
        }
        .tag {
            background: rgba(255, 255, 255, 0.05);
            color: #cbd5e1;
            font-size: 11.5px;
            padding: 4px 10px;
            border-radius: 8px;
            border: 1px solid rgba(255, 255, 255, 0.06);
        }
        
        /* Spacing & Styling for Google SSO Button */
        div[data-testid="stLinkButton"] {
            display: flex !important;
            justify-content: center !important;
            margin-top: 24px !important;
            margin-bottom: 50px !important;
        }
        div[data-testid="stLinkButton"] > a {
            background-color: #ffffff !important;
            color: #202124 !important;
            border: 1px solid #dadce0 !important;
            border-radius: 10px !important;
            font-size: 15px !important;
            font-weight: 600 !important;
            padding: 12px 28px !important;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2) !important;
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            gap: 10px !important;
            transition: all 0.2s ease-in-out !important;
            max-width: 340px !important;
            width: 100% !important;
            text-decoration: none !important;
        }
        div[data-testid="stLinkButton"] > a:hover {
            background-color: #f1f3f4 !important;
            box-shadow: 0 6px 16px rgba(0, 0, 0, 0.3) !important;
            transform: translateY(-1px) !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown(
            """
            <div class="login-card-wrapper">
                <span class="kube-badge">⚡ PRODUCTION MULTI-AGENT RAG</span>
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
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.link_button(
            "🚀 Continue with Google",
            get_google_auth_url(),
            use_container_width=True,
        )

    st.stop()


# ==============================================================================
# 2. AUTHENTICATED CHATBOT APPLICATION (ChatGPT / Gemini Style)
# ==============================================================================

user_id = current_user["user_id"]
user_name = current_user.get("name", "User")
user_email = current_user.get("email", "")
user_picture = current_user.get("picture")


def fetch_user_threads(u_id: str):
    """Fetch user threads from backend with generous timeout."""
    try:
        resp = api_request("GET", f"/api/users/{u_id}/threads", timeout=10)
        if resp.status_code == 200:
            return resp.json().get("threads", [])
    except Exception as e:
        print(f"Could not load chat threads: {e}")
    return []


# Maintain cached threads list in session_state to avoid repeated HTTP calls
if "threads" not in st.session_state or st.session_state.get("threads_user") != user_id:
    st.session_state.threads = fetch_user_threads(user_id)
    st.session_state.threads_user = user_id

threads = st.session_state.threads or []

# Initialize active thread if none exists
if "current_thread_id" not in st.session_state or not st.session_state.current_thread_id:
    if threads:
        st.session_state.current_thread_id = threads[0]["thread_id"]
    else:
        new_id = str(uuid.uuid4())
        st.session_state.current_thread_id = new_id
        st.session_state.loaded_thread_id = new_id
        st.session_state.messages = []

# Load Messages for current thread from backend on switch
if "messages" not in st.session_state or st.session_state.get("loaded_thread_id") != st.session_state.current_thread_id:
    st.session_state.messages = []
    curr_id = st.session_state.current_thread_id
    if curr_id:
        try:
            hist_resp = api_request(
                "GET",
                f"/api/threads/{curr_id}/history",
                timeout=10,
            )
            if hist_resp.status_code == 200:
                db_messages = hist_resp.json().get("messages", [])
                st.session_state.messages = [
                    {
                        "role": m["role"],
                        "content": m["content"],
                    }
                    for m in db_messages
                ]
        except Exception as e:
            print(f"Error loading thread history: {e}")
    st.session_state.loaded_thread_id = curr_id


# --- SIDEBAR (ChatGPT Style) ---
with st.sidebar:
    st.markdown("### ☸️ **Kubernetes AI**")

    # + New Chat Button (Instant 0ms Local Update)
    if st.button("➕ **New Chat**", use_container_width=True, type="primary"):
        new_id = str(uuid.uuid4())
        st.session_state.current_thread_id = new_id
        st.session_state.messages = []
        st.session_state.loaded_thread_id = new_id
        st.rerun()

    st.markdown("---")
    st.markdown("##### 💬 **Recent Conversations**")

    # Thread List with perfectly centered delete icon
    if threads:
        for t in threads:
            t_id = t["thread_id"]
            t_title = t.get("title") or "New Chat"
            is_active = t_id == st.session_state.current_thread_id

            col_btn, col_del = st.columns([5, 1], vertical_alignment="center")
            with col_btn:
                button_label = f"📍 {t_title}" if is_active else f"🗨️ {t_title}"
                if st.button(
                    button_label,
                    key=f"thread_btn_{t_id}",
                    use_container_width=True,
                    type="secondary" if not is_active else "primary",
                ):
                    if st.session_state.current_thread_id != t_id:
                        st.session_state.current_thread_id = t_id
                        st.session_state.loaded_thread_id = None
                        st.rerun()
            with col_del:
                if st.button("🗑️", key=f"del_{t_id}", help="Delete chat"):
                    # Fire background delete request without blocking UI
                    def _delete_bg(target_id, uid):
                        try:
                            api_request("DELETE", f"/api/threads/{target_id}?user_id={uid}", timeout=10)
                        except Exception as e:
                            print(f"Background thread delete error: {e}")

                    import threading
                    threading.Thread(target=_delete_bg, args=(t_id, user_id), daemon=True).start()

                    # Instantly update local session state
                    st.session_state.threads = [x for x in (st.session_state.threads or []) if x["thread_id"] != t_id]
                    if st.session_state.current_thread_id == t_id:
                        if st.session_state.threads:
                            st.session_state.current_thread_id = st.session_state.threads[0]["thread_id"]
                        else:
                            st.session_state.current_thread_id = str(uuid.uuid4())
                        st.session_state.loaded_thread_id = None
                        st.session_state.messages = []
                    st.rerun()
    else:
        st.caption("No previous chats found. Start a new conversation!")

    st.markdown("---")

    # System Status Indicators
    st.caption(f"🟢 **Logfire:** {LOGFIRE_STATUS}")
    if st.session_state.current_thread_id:
        st.caption(f"🔑 **Thread ID:** `{st.session_state.current_thread_id[:8]}`")

    st.markdown("---")

    # User Profile Pill (Bottom of Sidebar - Full Name & Clean Email)
    avatar_html = f'<img src="{user_picture}" style="width: 38px; height: 38px; border-radius: 50%; object-fit: cover;" />' if user_picture else f'<div style="width: 38px; height: 38px; border-radius: 50%; background: #00838f; display: flex; align-items: center; justify-content: center; font-size: 16px; font-weight: 600; color: #fff;">{user_name[0].upper() if user_name else "U"}</div>'

    st.markdown(
        f"""
        <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 12px; padding: 4px 0;">
            {avatar_html}
            <div style="overflow: hidden; flex: 1;">
                <div style="font-weight: 600; font-size: 14px; color: #ffffff; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{user_name}</div>
                <div style="font-size: 12px; color: #9aa0a6; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 170px;" title="{user_email}">{user_email}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.button("🚪 **Sign Out**", use_container_width=True):
        logout_user()


# ==============================================================================
# 3. MAIN CHAT AREA
# ==============================================================================

# Find current thread title
current_title = "New Chat"
for t in (threads or []):
    if t["thread_id"] == st.session_state.current_thread_id:
        current_title = t.get("title", "New Chat")
        break

st.title(f"🤖 {current_title}")

# Render Clean Chat History (No clutter or unwanted source expanders on old messages)
for message in st.session_state.messages:
    avatar = AI_AVATAR if message["role"] == "assistant" else USER_AVATAR
    with st.chat_message(message["role"], avatar=avatar):
        st.markdown(clean_think_tags(message["content"]))


# Chat Input Box
if prompt := st.chat_input("Ask about your documentation..."):
    # 1. Append User Message
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user", avatar=USER_AVATAR):
        st.markdown(prompt)

    # Pre-compute title if this is a new chat
    curr_id = st.session_state.current_thread_id
    clean_t = prompt.strip().replace("\n", " ")
    if len(clean_t) > 35:
        clean_t = clean_t[:32] + "..."
    clean_title = clean_t.capitalize()

    # 2. Assistant Response
    with st.chat_message("assistant", avatar=AI_AVATAR):
        full_answer = ""
        sources = []
        steps = []
        is_conversational = False

        with st.status("🔍 Agent is thinking...", expanded=True) as status:
            try:
                with logfire.span("Calling RAG Backend"):
                    payload = {
                        "q": prompt,
                        "query": prompt,
                        "thread_id": curr_id,
                        "user_id": user_id,
                    }
                    headers = {
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {os.getenv('RAG_API_KEY', '')}",
                    }
                    response = api_request("POST", "/query", json_data=payload, headers=headers, timeout=180)
                    data = response.json() if hasattr(response, "json") else {}

                if response.status_code != 200:
                    err_msg = data.get("message") or data.get("detail") or f"HTTP {response.status_code}"
                    raise RuntimeError(err_msg)

                status_text = data.get("status", "")
                if "conversationally" in status_text.lower() or "memory" in status_text.lower():
                    is_conversational = True

                # Guardrails block
                if data.get("status") == "Blocked by guardrails.":
                    status.update(label="🛡️ Blocked by guardrails", state="complete", expanded=False)
                    raw_answer = data.get("answer", "Blocked by guardrails.")
                    full_answer = clean_think_tags(raw_answer)

                elif "answer" in data or "response" in data:
                    status.update(label="✅ Answer Synthesized", state="complete", expanded=False)
                    raw_answer = data.get("answer") or data.get("response") or "No response."
                    full_answer = clean_think_tags(raw_answer)
                    sources = data.get("sources", [])
                    steps = data.get("thought_process", [])

                else:
                    raise RuntimeError(f"Unexpected response from backend: {data}")

                # Display reasoning steps
                for step in steps:
                    st.write(f"⚙️ {step}")

                # Display sources ONLY if technical/RAG (not conversational greetings)
                if sources and not is_conversational:
                    with st.expander(f"📄 View Retrieved Context ({len(sources)} sources)"):
                        for i, source in enumerate(sources):
                            preview = str(source)[:100].replace("\n", " ") + "..."
                            with st.expander(f"Chunk {i + 1}: {preview}"):
                                st.info(source)

            except Exception as e:
                logfire.error(f"UI-Backend Execution Error: {e}")
                status.update(label=f"❌ Request Failed", state="error", expanded=True)
                st.error(f"Execution Error: {e}")
                st.stop()

        # Stream Final Answer smoothly
        answer_placeholder = st.empty()
        curr_text = ""
        for char in full_answer:
            curr_text += char
            answer_placeholder.markdown(curr_text + "▌")
            time.sleep(0.002)

        answer_placeholder.markdown(full_answer)
        st.session_state.messages.append({
            "role": "assistant",
            "content": full_answer,
        })

        # Update in-memory threads list with the new title
        existing = next((x for x in (st.session_state.threads or []) if x["thread_id"] == curr_id), None)
        if existing:
            if existing.get("title") in ("New Chat", "", None):
                existing["title"] = clean_title
        else:
            st.session_state.threads = [{"thread_id": curr_id, "title": clean_title}] + (st.session_state.threads or [])

        logfire.info("Chat cycle completed successfully.")
        st.rerun()