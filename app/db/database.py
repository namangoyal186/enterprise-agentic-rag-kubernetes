"""
Database layer for Enterprise Agentic RAG.
Manages users, multi-user chat threads, and message persistence in PostgreSQL (Neon).
Uses a high-performance ConnectionPool to eliminate per-request connection latency.
"""
import json
import logging
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Generator, List, Optional

import logfire
import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import settings

logger = logging.getLogger(__name__)

_pool: Optional[ConnectionPool] = None


def get_connection_pool() -> Optional[ConnectionPool]:
    """Get or initialize the shared database connection pool."""
    global _pool
    if _pool is None and settings.postgres_uri:
        try:
            _pool = ConnectionPool(
                conninfo=settings.postgres_uri,
                min_size=2,
                max_size=20,
                timeout=10,
                max_idle=300,
                check=ConnectionPool.check_connection,
                kwargs={"row_factory": dict_row},
                open=False,
            )
            _pool.open()
            logfire.info("🗄️ Database ConnectionPool initialized.")
        except Exception as e:
            logfire.warning(f"⚠️ Could not create ConnectionPool: {e}")
            _pool = None
    return _pool


@contextmanager
def get_db_connection() -> Generator[psycopg.Connection, None, None]:
    """Yield a connection from the pool, or fallback to direct connect."""
    pool = get_connection_pool()
    if pool:
        with pool.connection() as conn:
            yield conn
    else:
        if not settings.postgres_uri:
            raise ValueError("NEON_DB_URL is not set in environment.")
        with psycopg.connect(settings.postgres_uri, row_factory=dict_row) as conn:
            yield conn


def init_db() -> bool:
    """
    Initialize database schema (users, chat_threads, thread_messages).
    Safe to run multiple times (idempotent).
    """
    if not settings.postgres_uri:
        logfire.warning("⚠️ NEON_DB_URL not configured. Database initialization skipped.")
        return False

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # 1. Users Table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        user_id VARCHAR(255) PRIMARY KEY,
                        email VARCHAR(255) UNIQUE NOT NULL,
                        name VARCHAR(255),
                        picture_url TEXT,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        last_login TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    );
                """)

                # 2. Chat Threads Table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS chat_threads (
                        thread_id VARCHAR(64) PRIMARY KEY,
                        user_id VARCHAR(255) REFERENCES users(user_id) ON DELETE CASCADE,
                        title VARCHAR(255) NOT NULL DEFAULT 'New Chat',
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE INDEX IF NOT EXISTS idx_chat_threads_user_id ON chat_threads(user_id);
                    CREATE INDEX IF NOT EXISTS idx_chat_threads_updated_at ON chat_threads(updated_at DESC);
                """)

                # 3. Thread Messages Table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS thread_messages (
                        id BIGSERIAL PRIMARY KEY,
                        thread_id VARCHAR(64) REFERENCES chat_threads(thread_id) ON DELETE CASCADE,
                        role VARCHAR(32) NOT NULL,
                        content TEXT NOT NULL,
                        sources JSONB DEFAULT '[]'::jsonb,
                        thought_process JSONB DEFAULT '[]'::jsonb,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE INDEX IF NOT EXISTS idx_thread_messages_thread_id ON thread_messages(thread_id, id ASC);
                """)
            conn.commit()
        logfire.info("🗄️ PostgreSQL database schema initialized successfully.")
        return True
    except Exception as e:
        logfire.error(f"❌ Failed to initialize database: {e}")
        print(f"Database init error: {e}")
        return False


def upsert_user(user_id: str, email: str, name: Optional[str] = None, picture_url: Optional[str] = None) -> Dict[str, Any]:
    """Insert or update user record from Google OAuth login."""
    if not settings.postgres_uri:
        return {"user_id": user_id, "email": email, "name": name, "picture_url": picture_url}

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users (user_id, email, name, picture_url, last_login)
                VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (user_id) DO UPDATE SET
                    email = EXCLUDED.email,
                    name = COALESCE(EXCLUDED.name, users.name),
                    picture_url = COALESCE(EXCLUDED.picture_url, users.picture_url),
                    last_login = CURRENT_TIMESTAMP
                RETURNING user_id, email, name, picture_url, created_at, last_login;
            """, (user_id, email, name, picture_url))
            row = cur.fetchone()
        conn.commit()
        return dict(row) if row else {}


def create_chat_thread(thread_id: str, user_id: str, title: str = "New Chat") -> Dict[str, Any]:
    """Create a new chat thread for a user."""
    if not settings.postgres_uri:
        return {"thread_id": thread_id, "user_id": user_id, "title": title}

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users (user_id, email, name)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id) DO NOTHING;
            """, (user_id, f"{user_id}@example.com", user_id))

            cur.execute("""
                INSERT INTO chat_threads (thread_id, user_id, title, created_at, updated_at)
                VALUES (%s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT (thread_id) DO UPDATE SET
                    updated_at = CURRENT_TIMESTAMP
                RETURNING thread_id, user_id, title, created_at, updated_at;
            """, (thread_id, user_id, title))
            row = cur.fetchone()
        conn.commit()
        return dict(row) if row else {}


def get_user_threads(user_id: str) -> List[Dict[str, Any]]:
    """Retrieve all chat threads for a user, sorted by most recently updated."""
    if not settings.postgres_uri:
        return []

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT thread_id, user_id, title, created_at, updated_at
                FROM chat_threads
                WHERE user_id = %s
                ORDER BY updated_at DESC;
            """, (user_id,))
            rows = cur.fetchall()
        return [dict(r) for r in rows]


def get_thread_messages(thread_id: str) -> List[Dict[str, Any]]:
    """Get all messages for a specific chat thread in chronological order."""
    if not settings.postgres_uri:
        return []

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, thread_id, role, content, sources, thought_process, created_at
                FROM thread_messages
                WHERE thread_id = %s
                ORDER BY id ASC;
            """, (thread_id,))
            rows = cur.fetchall()
        return [dict(r) for r in rows]


def add_thread_message(
    thread_id: str,
    role: str,
    content: str,
    sources: Optional[List[Any]] = None,
    thought_process: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    """Add a message to a thread and touch the thread's updated_at timestamp."""
    if not settings.postgres_uri:
        return {"thread_id": thread_id, "role": role, "content": content}

    sources_json = json.dumps(sources or [])
    thought_json = json.dumps(thought_process or [])

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO thread_messages (thread_id, role, content, sources, thought_process, created_at)
                VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, CURRENT_TIMESTAMP)
                RETURNING id, thread_id, role, content, sources, thought_process, created_at;
            """, (thread_id, role, content, sources_json, thought_json))
            msg_row = cur.fetchone()

            cur.execute("""
                UPDATE chat_threads
                SET updated_at = CURRENT_TIMESTAMP
                WHERE thread_id = %s;
            """, (thread_id,))
        conn.commit()
        return dict(msg_row) if msg_row else {}


def update_thread_title(thread_id: str, title: str) -> bool:
    """Update title of a chat thread."""
    if not settings.postgres_uri:
        return False

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE chat_threads
                SET title = %s, updated_at = CURRENT_TIMESTAMP
                WHERE thread_id = %s;
            """, (title, thread_id))
            affected = cur.rowcount
        conn.commit()
        return affected > 0


def delete_chat_thread(thread_id: str, user_id: Optional[str] = None) -> bool:
    """Delete a chat thread and all its messages / LangGraph checkpoints."""
    if not settings.postgres_uri:
        return False

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            if user_id:
                cur.execute("DELETE FROM chat_threads WHERE thread_id = %s AND user_id = %s;", (thread_id, user_id))
            else:
                cur.execute("DELETE FROM chat_threads WHERE thread_id = %s;", (thread_id,))
            affected = cur.rowcount

            try:
                cur.execute("DELETE FROM checkpoints WHERE thread_id = %s;", (thread_id,))
                cur.execute("DELETE FROM checkpoint_blobs WHERE thread_id = %s;", (thread_id,))
                cur.execute("DELETE FROM checkpoint_writes WHERE thread_id = %s;", (thread_id,))
            except Exception:
                pass
        conn.commit()
        return affected > 0
