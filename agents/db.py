import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from supabase import Client, create_client

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=ENV_FILE)


@lru_cache(maxsize=1)
def get_supabase_client() -> Optional[Client]:
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url or not key:
        return None
    try:
        return create_client(url, key)
    except Exception:
        return None


def is_db_available() -> bool:
    return get_supabase_client() is not None


def fetch_nodes(limit: int = 200) -> list[dict[str, Any]]:
    client = get_supabase_client()
    if client is None:
        return []

    capped_limit = max(1, min(limit, 500))
    try:
        response = client.table("nodes").select("*").limit(capped_limit).execute()
    except Exception:
        return []
    return response.data or []


supabase = get_supabase_client()
