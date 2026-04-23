# ingestion/db_insert.py

import os
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from supabase import create_client, Client


# Load .env from project root
load_dotenv()

_supabase: Optional[Client] = None


def get_client() -> Client:
    """
    Lazy-load Supabase client so imports don't crash app startup.
    """
    global _supabase

    if _supabase is not None:
        return _supabase

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")

    if not url:
        raise ValueError("Missing SUPABASE_URL in .env")

    if not key:
        raise ValueError("Missing SUPABASE_KEY in .env")

    _supabase = create_client(url, key)
    return _supabase


def insert_decision(data: Dict[str, Any], source_url: str = "") -> Dict[str, Any]:
    """
    Insert extracted webhook decision into nodes table.

    Expected incoming data examples:
    {
        "label": "approved gateway rate limiting",
        "type": "decision",
        "metadata": {...}
    }

    Flexible enough if extractor output varies.
    """
    try:
        supabase = get_client()

        label = data.get("label") or data.get("decision") or "unknown"
        node_type = data.get("type") or "decision"
        metadata = data.get("metadata") or data

        payload = {
            "label": str(label),
            "type": str(node_type),
            "metadata": metadata,
            "source_url": source_url
        }

        result = (
            supabase
            .table("nodes")
            .insert(payload)
            .execute()
        )

        return {
            "success": True,
            "inserted": payload,
            "response": result.data if hasattr(result, "data") else None
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }