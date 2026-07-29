import os
from typing import Any
from uuid import UUID

from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from supabase import AuthApiError

try:
    from .db import get_client
except ImportError:
    from db import get_client

security = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Security(security),
) -> dict[str, Any]:
    if not credentials:
        raise HTTPException(status_code=401, detail="Authentication credentials are required.")

    token = credentials.credentials
    if not token or not token.strip():
        raise HTTPException(status_code=401, detail="Authentication token is missing.")

    client = get_client()
    if not client:
        raise HTTPException(status_code=500, detail="Database client is not initialized.")

    try:
        user_response = client.auth.get_user(token)
        if not user_response or not user_response.user:
            raise HTTPException(status_code=401, detail="Invalid session or user not found.")

        user = user_response.user
        return {
            "id": user.id,
            "email": user.email,
            "user_metadata": user.user_metadata or {},
        }
    except AuthApiError as exc:
        raise HTTPException(status_code=401, detail=f"Authentication failed: {exc.message}") from exc
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Authentication failed: {exc}") from exc


def get_optional_current_user(
    credentials: HTTPAuthorizationCredentials | None = Security(security),
) -> dict[str, Any] | None:
    if not credentials or not credentials.credentials or not credentials.credentials.strip():
        return None

    client = get_client()
    if not client:
        return None

    try:
        user_response = client.auth.get_user(credentials.credentials)
        if not user_response or not user_response.user:
            return None

        user = user_response.user
        return {
            "id": user.id,
            "email": user.email,
            "user_metadata": user.user_metadata or {},
        }
    except Exception:
        return None
