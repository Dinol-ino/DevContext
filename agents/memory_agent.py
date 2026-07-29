from typing import Any, List, Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

try:
    from .auth_utils import get_current_user
    from .db import (
        add_chat_message,
        create_chat_thread,
        delete_chat_thread,
        fetch_chat_messages,
        get_chat_thread,
        list_chat_threads,
    )
except ImportError:
    from auth_utils import get_current_user
    from db import (
        add_chat_message,
        create_chat_thread,
        delete_chat_thread,
        fetch_chat_messages,
        get_chat_thread,
        list_chat_threads,
    )

router = APIRouter(tags=["Memory"])


class ThreadCreateRequest(BaseModel):
    title: Optional[str] = Field(default="New Conversation", max_length=200)
    repo_id: Optional[str] = Field(default=None)


class ThreadResponse(BaseModel):
    id: str
    user_id: Optional[str] = None
    repo_id: Optional[str] = None
    title: str
    created_at: str
    updated_at: str


class MessageResponse(BaseModel):
    id: str
    thread_id: str
    role: str
    content: str
    confidence: Optional[float] = None
    sources: List[dict] = Field(default_factory=list)
    used_model: Optional[str] = None
    created_at: str


@router.post("/chat/threads", response_model=ThreadResponse)
def create_thread(
    payload: ThreadCreateRequest,
    current_user: dict = Depends(get_current_user),
) -> ThreadResponse:
    try:
        user_id = current_user.get("id") if isinstance(current_user, dict) else None
        thread = create_chat_thread(user_id=user_id, repo_id=payload.repo_id, title=payload.title or "New Conversation")
        return ThreadResponse(
            id=str(thread["id"]),
            user_id=str(thread.get("user_id")) if thread.get("user_id") else None,
            repo_id=str(thread.get("repo_id")) if thread.get("repo_id") else None,
            title=str(thread.get("title", "New Conversation")),
            created_at=str(thread.get("created_at", "")),
            updated_at=str(thread.get("updated_at", "")),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to create chat thread: {exc}") from exc


@router.get("/chat/threads", response_model=List[ThreadResponse])
def list_threads(
    repo_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
) -> List[ThreadResponse]:
    try:
        user_id = current_user.get("id") if isinstance(current_user, dict) else None
        threads = list_chat_threads(user_id=user_id, repo_id=repo_id)
        return [
            ThreadResponse(
                id=str(t["id"]),
                user_id=str(t.get("user_id")) if t.get("user_id") else None,
                repo_id=str(t.get("repo_id")) if t.get("repo_id") else None,
                title=str(t.get("title", "Conversation")),
                created_at=str(t.get("created_at", "")),
                updated_at=str(t.get("updated_at", "")),
            )
            for t in threads
        ]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to list chat threads: {exc}") from exc


@router.get("/chat/threads/{thread_id}/messages", response_model=List[MessageResponse])
def get_thread_messages(
    thread_id: str,
    current_user: dict = Depends(get_current_user),
) -> List[MessageResponse]:
    thread = get_chat_thread(thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found.")

    try:
        messages = fetch_chat_messages(thread_id)
        return [
            MessageResponse(
                id=str(m["id"]),
                thread_id=str(m["thread_id"]),
                role=str(m["role"]),
                content=str(m["content"]),
                confidence=float(m["confidence"]) if m.get("confidence") is not None else None,
                sources=m.get("sources") if isinstance(m.get("sources"), list) else [],
                used_model=str(m.get("used_model")) if m.get("used_model") else None,
                created_at=str(m.get("created_at", "")),
            )
            for m in messages
        ]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch thread messages: {exc}") from exc


@router.delete("/chat/threads/{thread_id}")
def delete_thread(
    thread_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    success = delete_chat_thread(thread_id)
    if not success:
        raise HTTPException(status_code=404, detail="Thread not found or could not be deleted.")
    return {"status": "deleted", "id": thread_id}
