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

try:
    from auth import (
        GOOGLE_CLIENT_ID,
        get_google_auth_url,
        handle_oauth_flow,
        logout_user,
    )
except (ImportError, KeyError):
    from ui.auth import (
        GOOGLE_CLIENT_ID,
        get_google_auth_url,
        handle_oauth_flow,
        logout_user,
    )

# Load environment variables explicitly from the root directory
env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
load_dotenv(dotenv_path=env_path)

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")


@st.cache_resource
def get_inprocess_client():
    """Cache in-process FastAPI TestClient for zero-latency execution on cloud/local."""
    try:
        from fastapi.testclient import TestClient
        from app.main import app
        return TestClient(app)
    except Exception as e:
        logfire.warning(f"In-process client init note: {e}")
        return None


def api_request(method: str, path: str, json_data: dict = None, headers: dict = None, timeout: int = 120):
    """
    Unified API dispatcher:
    - If BACKEND_URL starts with 'https://', sends standard network HTTP request.
    - Otherwise, routes in-process directly to the FastAPI agent app (0ms latency, single-container full stack).
    """
    if BACKEND_URL.startswith("https://"):
        url = f"{BACKEND_URL}{path}"
        if method.upper() == "GET":
            return requests.get(url, headers=headers, timeout=timeout)
        elif method.upper() == "POST":
            return requests.post(url, json=json_data, headers=headers, timeout=timeout)
        elif method.upper() == "DELETE":
            return requests.delete(url, headers=headers, timeout=timeout)
    else:
        client = get_inprocess_client()
        if client is not None:
            if method.upper() == "GET":
                return client.get(path, headers=headers)
            elif method.upper() == "POST":
                return client.post(path, json=json_data, headers=headers)
            elif method.upper() == "DELETE":
                return client.delete(path, headers=headers)
        # Fallback to local HTTP
        url = f"{BACKEND_URL}{path}"
        if method.upper() == "GET":
            return requests.get(url, headers=headers, timeout=timeout)
        elif method.upper() == "POST":
            return requests.post(url, json=json_data, headers=headers, timeout=timeout)
        elif method.upper() == "DELETE":
            return requests.delete(url, headers=headers, timeout=timeout)


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
    page_title="Agent OS - Enterprise RAG",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded" if is_authenticated else "collapsed",
)

# Custom CSS for polished alignment, hide top header/deploy options, disable grey overlay
hide_sidebar_css = "[data-testid=\"stSidebar\"], [data-testid=\"collapsedControl\"] { display: none !important; }" if not is_authenticated else ""

st.markdown(
    f"""
    <style>
    /* Hide Streamlit header, deploy button, and 3-dots toolbar */
    header[data-testid="stHeader"] {{
        display: none !important;
    }}
    [data-testid="stToolbar"] {{
        display: none !important;
    }}
    .stDeployButton {{
        display: none !important;
    }}
    footer {{
        display: none !important;
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
        .google-btn {
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
            text-decoration: none;
            box-shadow: 0 2px 4px rgba(0,0,0,0.2);
            transition: background-color 0.2s, box-shadow 0.2s;
            margin-top: 20px;
        }
        .google-btn:hover {
            background-color: #f8f9fa;
            box-shadow: 0 4px 8px rgba(0,0,0,0.3);
            color: #202124;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown(
            f"""
            <div class="login-card">
                <h1 style="margin-bottom: 8px;">🧠 Agent OS</h1>
                <p style="color: #9aa0a6; font-size: 15px; margin-bottom: 24px;">
                    Enterprise Multi-Agent RAG with Persistent Memory & Guardrails
                </p>
                <a href="{get_google_auth_url()}" target="_self" class="google-btn">
                    <svg width="20" height="20" viewBox="0 0 48 48">
                        <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>
                        <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>
                        <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>
                        <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>
                    </svg>
                    Continue with Google
                </a>
            </div>
            """,
            unsafe_allow_html=True,
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
    st.markdown("### 🧠 **Agent OS**")

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
                    data = response.json()

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
                logfire.error(f"UI-Backend Connection Failed: {e}")
                status.update(label="❌ Connection Failed", state="error")
                st.error(f"Backend offline or error: {e}")
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