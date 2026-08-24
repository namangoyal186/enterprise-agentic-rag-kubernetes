# ============================================================
# CRITICAL: logfire MUST be configured before ALL other imports
# so that spans from all modules are captured from the start.
# ============================================================
import logfire

from app.config import settings

# Logfire v2 EU tokens start with "pylf_v2_eu_" and must send spans to the
# EU endpoint. If no base URL is configured, infer it from the token prefix
# so the same .env works locally and inside Docker without manual overrides.
_logfire_base_url = settings.LOGFIRE_BASE_URL
if not _logfire_base_url and settings.LOGFIRE_TOKEN:
    if settings.LOGFIRE_TOKEN.startswith("pylf_v2_eu_"):
        _logfire_base_url = "https://logfire-eu.pydantic.dev"

logfire.configure(
    token=settings.LOGFIRE_TOKEN,
    advanced=logfire.AdvancedOptions(base_url=_logfire_base_url) if _logfire_base_url else None,
)

import os
import time
import uuid
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from prometheus_client import Counter, Histogram
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel

from app.agents.graph import build_graph
from app.db.database import (
    add_thread_message,
    create_chat_thread,
    init_db,
    update_thread_title,
)
from app.guardrails import guard, initialize_rails
from app.health import router as health_router
from app.logging import set_request_id
from app.routers.threads import router as threads_router
from app.services.auth import (
    SESSION_COOKIE_NAME,
    create_session_token,
    exchange_code_for_user,
    get_google_auth_url,
    get_redirect_uri,
    verify_session_token,
)
from app.services.health.connection_checker import check_all_connections, log_connection_summary

app = FastAPI(title="Enterprise Agentic RAG API")

# Enable CORS for local & production origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Static Files
static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

app.include_router(health_router)
app.include_router(threads_router)

# Custom Prometheus metrics
RAG_REQUESTS_TOTAL = Counter(
    "rag_requests_total",
    "Total number of /query requests",
    ["status"],
)
RAG_REQUEST_DURATION = Histogram(
    "rag_request_duration_seconds",
    "Latency of /query requests in seconds",
)
GUARDRAILS_BLOCKS_TOTAL = Counter(
    "guardrails_blocks_total",
    "Number of requests blocked or allowed by guardrails",
    ["blocked"],
)

_security = HTTPBearer(auto_error=False)


def _init_rate_limiter():
    """Initialize rate limiting. Use Redis in production; fall back to in-memory storage locally."""
    from limits.storage import RedisStorage
    from slowapi import Limiter
    from slowapi.errors import RateLimitExceeded
    from slowapi.extension import _rate_limit_exceeded_handler
    from slowapi.util import get_remote_address

    try:
        storage = RedisStorage(settings.redis_url)
        # `storage.check()` returns False silently on some failures; ping the
        # underlying Redis client so we only use Redis when it is really reachable.
        if not storage.check() or not storage.storage.ping():
            raise ConnectionError("Redis did not respond to ping")
        app.state.limiter = Limiter(key_func=get_remote_address, storage_uri=settings.redis_url)
        app.state.rate_limiter_storage = "redis"
        logfire.info("🚦 Rate limiting initialized via Redis.")
    except Exception as e:
        app.state.limiter = Limiter(key_func=get_remote_address)
        app.state.rate_limiter_storage = "memory"
        logfire.warning(f"⚠️ Redis unavailable ({e}); using in-memory rate limiting.")

    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    return True


def verify_api_key(credentials: HTTPAuthorizationCredentials = Depends(_security)):
    """
    Require a valid bearer token when RAG_API_KEY is configured.
    In development, omit RAG_API_KEY to disable authentication.
    """
    if not settings.API_KEY:
        # Development mode: no API key required.
        return None

    if not credentials or credentials.credentials != settings.API_KEY:
        logfire.warning("🔒 Unauthorized /query request: invalid or missing API key.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials


def _get_limiter_rule(times: int, seconds: int) -> str:
    """Convert times/seconds into a slowapi limit string, e.g. '20/minute'."""
    if seconds % 60 == 0:
        return f"{times}/{seconds // 60}minute"
    if seconds % 3600 == 0:
        return f"{times}/{seconds // 3600}hour"
    return f"{times}/{seconds}second"


class _AppLimiter:
    """
    Thin wrapper around the Limiter instance that is initialized at startup.
    Allows routes to be decorated at import time while the real limiter
    (Redis-backed or in-memory) is configured in startup_event.
    """

    def limit(self, rule_or_callable):
        def decorator(func):
            import functools

            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                limiter = getattr(app.state, "limiter", None)
                if limiter is None:
                    return func(*args, **kwargs)

                rule = rule_or_callable() if callable(rule_or_callable) else rule_or_callable
                # Build the slowapi wrapper at request time so the limiter
                # instance and storage backend are always current.
                return limiter.limit(rule)(func)(*args, **kwargs)

            return wrapper

        return decorator


app_limiter = _AppLimiter()


def rate_limit(times: int = None, seconds: int = None):
    """
    Decorator factory that applies slowapi rate limiting using the limiter
    initialized at startup. Falls back to a no-op if the limiter is missing.
    The rule is resolved at request time so settings can be overridden in tests.
    """

    def _resolve_rule() -> str:
        t = times or settings.RATE_LIMIT_PER_MINUTE
        s = seconds or 60
        return _get_limiter_rule(t, s)

    return app_limiter.limit(_resolve_rule)


# Initialize FastAPI



# Expose Prometheus metrics at /metrics with default request instrumentation.
Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)


@app.on_event("startup")
def startup_event():
    # 1. Ultra-fast startup (<10ms) so uvicorn binds port instantly for Render health checks
    app.state.rate_limiter_enabled = _init_rate_limiter()

    # 2. Initialize PostgreSQL schema and warm up heavy models in background
    def _async_warmup():
        try:
            init_db()
        except Exception as e:
            logfire.warning(f"init_db notice: {e}")

        try:
            initialize_rails()
        except Exception as e:
            logfire.warning(f"initialize_rails notice: {e}")

        try:
            app.state.rag_agent = build_graph()
        except Exception as e:
            logfire.warning(f"build_graph notice: {e}")

        try:
            connection_results = check_all_connections()
            log_connection_summary(connection_results)
        except Exception as e:
            logfire.warning(f"Background connection check: {e}")

    import threading
    threading.Thread(target=_async_warmup, daemon=True).start()

    if not settings.API_KEY:
        logfire.warning("🔓 RAG_API_KEY is not set — /query is open to anyone. Set it in production.")



class QueryRequest(BaseModel):
    q: str
    thread_id: Optional[str] = "default_user"
    user_id: Optional[str] = "default_user"


# ==============================================================================
# FRONTEND & AUTHENTICATION ENDPOINTS (Instant <50ms Load)
# ==============================================================================

@app.get("/")
def serve_ui(request: Request, code: Optional[str] = None, error: Optional[str] = None):
    """
    Serves the ultra-fast, pre-rendered HTML frontend directly.
    Also handles OAuth callback seamlessly if Google redirects to root (/?code=...).
    """
    if code:
        return auth_callback(request, code=code, error=error)

    index_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file, media_type="text/html")
    return {"message": "Enterprise LangGraph RAG API is live."}



@app.get("/auth/login")
def auth_login(request: Request):
    """Redirects the browser directly to Google OAuth 2.0."""
    host_url = str(request.base_url).rstrip("/")
    redirect_uri = get_redirect_uri(host_url)
    auth_url = get_google_auth_url(redirect_uri)
    return RedirectResponse(url=auth_url, status_code=status.HTTP_302_FOUND)


@app.get("/auth/callback")
def auth_callback(request: Request, code: Optional[str] = None, error: Optional[str] = None):
    """
    Handles Google OAuth redirect.
    Exchanges code for tokens in <200ms, sets secure HttpOnly cookie, and redirects to /.
    """
    if error or not code:
        logfire.warning(f"OAuth callback error: {error or 'No code provided'}")
        return RedirectResponse(url="/?error=oauth_failed", status_code=status.HTTP_302_FOUND)

    host_url = str(request.base_url).rstrip("/")
    redirect_uri = get_redirect_uri(host_url)

    user_data, err_msg = exchange_code_for_user(code, redirect_uri)
    if not user_data:
        logfire.error(f"Failed to exchange OAuth code: {err_msg}")
        return RedirectResponse(url=f"/?error={err_msg or 'oauth_exchange_failed'}", status_code=status.HTTP_302_FOUND)

    session_token = create_session_token(user_data)

    response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_token,
        max_age=30 * 24 * 60 * 60,  # 30 days
        path="/",
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https" or "render.com" in str(request.base_url),
    )
    return response


@app.get("/auth/me")
def auth_me(request: Request):
    """Returns the authenticated user's profile from the session cookie."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return {"user": None}

    user_data = verify_session_token(token)
    return {"user": user_data}


@app.post("/auth/logout")
def auth_logout(response: Response):
    """Clears the session cookie and signs out the user."""
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    return {"status": "logged_out"}



@app.get("/graph")
def get_graph_image(_api_key: str = Depends(verify_api_key)):
    """
    Returns the Mermaid image of the agent's workflow.
    """
    try:
        png_bytes = app.state.rag_agent.get_graph().draw_mermaid_png()
        return Response(content=png_bytes, media_type="image/png")
    except Exception as e:
        return {"error": f"Could not generate graph image: {e}"}


@app.post("/query")
@rate_limit()
def query(
    request: Request,
    body: QueryRequest,
    _api_key: str = Depends(verify_api_key),
):
    """
    Runs the LangGraph RAG pipeline synchronously.
    Returns the final answer, thought process, status, and sources.
    Persists user & assistant turns to PostgreSQL for chat history.
    """
    q = body.q
    thread_id = body.thread_id or "default_user"
    user_id = body.user_id or "default_user"
    request_id = str(uuid.uuid4())
    set_request_id(request_id)

    # Persist user turn to PostgreSQL
    try:
        create_chat_thread(thread_id=thread_id, user_id=user_id)
        add_thread_message(thread_id=thread_id, role="user", content=q)
    except Exception as e:
        logfire.warning(f"Failed to record user message to DB: {e}")

    start = time.perf_counter()
    with logfire.span("🔍 /query", request_id=request_id, thread_id=thread_id, user_id=user_id):
        # Gate: run guardrails synchronously so blocked requests never run the graph.
        rail_fired, rail_response = guard(q)
        if rail_fired:
            GUARDRAILS_BLOCKS_TOTAL.labels(blocked="true").inc()
            RAG_REQUESTS_TOTAL.labels(status="blocked").inc()
            RAG_REQUEST_DURATION.observe(time.perf_counter() - start)
            logfire.info("🛡️ Request blocked by guardrails", request_id=request_id, thread_id=thread_id)
            
            try:
                add_thread_message(
                    thread_id=thread_id,
                    role="assistant",
                    content=rail_response,
                    sources=[],
                    thought_process=["Intent: Guardrails Fired", "Retrieval: Skipped"],
                )
            except Exception:
                pass

            return {
                "question": q,
                "answer": rail_response,
                "thought_process": ["Intent: Guardrails Fired", "Retrieval: Skipped"],
                "status": "Blocked by guardrails.",
                "sources": [],
            }

        GUARDRAILS_BLOCKS_TOTAL.labels(blocked="false").inc()

        try:
            rag_agent = getattr(app.state, "rag_agent", None)
            if rag_agent is None:
                startup_event()
                rag_agent = getattr(app.state, "rag_agent", None)

            initial_state = {
                "messages": [{"role": "user", "content": q}],
                "current_query": q,
                "documents": [],
                "plan": ["Start"],
                "status": "Initializing Graph...",
            }
            config = {"configurable": {"thread_id": thread_id}}
            final_output = rag_agent.invoke(initial_state, config=config)

            answer = final_output.get("final_answer")
            thought_process = final_output.get("plan", [])
            sources = final_output.get("documents", [])

            # Persist assistant response to PostgreSQL
            try:
                add_thread_message(
                    thread_id=thread_id,
                    role="assistant",
                    content=answer or "",
                    sources=sources,
                    thought_process=thought_process,
                )
                # Auto-generate a descriptive thread title if it's the first message
                clean_title = q.strip().replace("\n", " ")
                if len(clean_title) > 40:
                    clean_title = clean_title[:37] + "..."
                update_thread_title(thread_id, clean_title.capitalize())
            except Exception as e:
                logfire.warning(f"Failed to record assistant message or update title: {e}")

            RAG_REQUESTS_TOTAL.labels(status="success").inc()
            RAG_REQUEST_DURATION.observe(time.perf_counter() - start)
            logfire.info(
                "✅ RAG pipeline completed",
                request_id=request_id,
                thread_id=thread_id,
            )
            return {
                "question": q,
                "answer": answer,
                "thought_process": thought_process,
                "status": final_output.get("status"),
                "sources": sources,
            }
        except Exception as e:
            RAG_REQUESTS_TOTAL.labels(status="error").inc()
            RAG_REQUEST_DURATION.observe(time.perf_counter() - start)
            logfire.error(
                f"❌ RAG pipeline failed: {e}",
                request_id=request_id,
                thread_id=thread_id,
            )
            return JSONResponse(
                status_code=500,
                content={
                    "request_id": request_id,
                    "status": "error",
                    "message": "Failed to process request. Please try again later.",
                },
            )
