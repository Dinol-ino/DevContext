import re
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

try:
    from .db import log_user_auth_event
except ImportError:
    from db import log_user_auth_event

router = APIRouter(tags=["Auth"])


class AuthEventRequest(BaseModel):
    event_type: Literal["register", "login"]
    email: str = Field(..., min_length=3, examples=["dev@company.com"])
    user_id: str | None = Field(default=None, examples=["8bcf3fd2-5666-472e-98eb-6e17943fd5b8"])
    provider: str = Field(default="email", examples=["email"])
    source: str = Field(default="frontend", examples=["frontend"])
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        val = v.strip().lower()
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", val):
            raise ValueError("Invalid email format")
        return val

    @field_validator("user_id")
    @classmethod
    def validate_user_id(cls, v: str | None) -> str | None:
        if v is None:
            return v
        val = v.strip()
        try:
            UUID(val)
        except ValueError:
            raise ValueError("user_id must be a valid UUID format")
        return val



class AuthEventResponse(BaseModel):
    status: str
    event_id: str | None = None
    event_type: str
    email: str


@router.post("/auth/log", response_model=AuthEventResponse)
def log_auth_event(payload: AuthEventRequest, request: Request) -> AuthEventResponse:
    try:
        stored = log_user_auth_event(
            event_type=payload.event_type,
            email=payload.email,
            user_id=payload.user_id,
            provider=payload.provider,
            source=payload.source,
            metadata=payload.metadata,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )

        return AuthEventResponse(
            status="logged",
            event_id=str(stored.get("id")) if stored.get("id") is not None else None,
            event_type=str(stored.get("auth_event") or payload.event_type),
            email=str(stored.get("email") or payload.email),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to log auth event: {exc}") from exc
