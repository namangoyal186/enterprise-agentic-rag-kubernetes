"""
API endpoints for User Authentication Sync, Multi-Chat Threads, and Message History.
"""
from typing import Any, Dict, List, Optional

import logfire
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.db.database import (
    add_thread_message,
    create_chat_thread,
    delete_chat_thread,
    get_thread_messages,
    get_user_threads,
    update_thread_title,
    upsert_user,
)

router = APIRouter(prefix="/api", tags=["Threads & Users"])


# --- PYDANTIC SCHEMAS ---

class UserSyncRequest(BaseModel):
    user_id: str = Field(..., description="Google Sub ID or unique user identifier")
    email: str = Field(..., description="User email address")
    name: Optional[str] = Field(None, description="User display name")
    picture_url: Optional[str] = Field(None, description="User avatar picture URL")


class CreateThreadRequest(BaseModel):
    thread_id: str = Field(..., description="Unique thread UUID")
    user_id: str = Field(..., description="Owner user ID")
    title: Optional[str] = Field("New Chat", description="Initial title for the thread")


class UpdateTitleRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255, description="New title for the thread")


# --- ENDPOINTS ---

@router.post("/users/sync")
def sync_user(body: UserSyncRequest):
    """
    Upsert user profile from Google OAuth login into PostgreSQL.
    """
    with logfire.span("Syncing User Profile", user_id=body.user_id, email=body.email):
        user = upsert_user(
            user_id=body.user_id,
            email=body.email,
            name=body.name,
            picture_url=body.picture_url,
        )
        return {"status": "success", "user": user}


@router.get("/users/{user_id}/threads")
def list_user_threads(user_id: str):
    """
    Get all chat threads for a user, sorted by most recently updated.
    """
    threads = get_user_threads(user_id)
    return {"status": "success", "threads": threads}


@router.post("/threads")
def create_thread(body: CreateThreadRequest):
    """
    Create a new chat thread for a user.
    """
    thread = create_chat_thread(
        thread_id=body.thread_id,
        user_id=body.user_id,
        title=body.title or "New Chat",
    )
    return {"status": "success", "thread": thread}


@router.get("/threads/{thread_id}/history")
def get_thread_history(thread_id: str):
    """
    Get all conversation messages for a specific chat thread.
    """
    messages = get_thread_messages(thread_id)
    return {"status": "success", "thread_id": thread_id, "messages": messages}


@router.patch("/threads/{thread_id}/title")
def update_title(thread_id: str, body: UpdateTitleRequest):
    """
    Update the title of a chat thread.
    """
    success = update_thread_title(thread_id, body.title)
    if not success:
        raise HTTPException(status_code=404, detail="Thread not found")
    return {"status": "success", "thread_id": thread_id, "title": body.title}


@router.delete("/threads/{thread_id}")
def delete_thread(thread_id: str, user_id: Optional[str] = Query(None)):
    """
    Delete a chat thread and all its history and checkpoints.
    """
    success = delete_chat_thread(thread_id, user_id)
    return {"status": "success", "thread_id": thread_id, "deleted": success}
