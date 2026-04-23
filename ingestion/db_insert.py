# ingestion/db_insert.py

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from supabase import Client, create_client

from .utils import log_error


def _load_env() -> None:
    root_env = Path(__file__).resolve().parents[1] / ".env"
    if root_env.exists():
        load_dotenv(dotenv_path=root_env, override=False)
    else:
        load_dotenv(override=False)


@lru_cache(maxsize=1)
def _get_supabase_client() -> Client:
    _load_env()
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()

    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be configured.")

    try:
        return create_client(url, key)
    except Exception as exc:
        log_error(f"Supabase client initialization failed: {exc}")
        raise RuntimeError(f"Failed to initialize Supabase client: {exc}") from exc


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _insert_node_row(node_type: str, label: str, metadata: dict[str, Any], source_url: str = "") -> str:
    client = _get_supabase_client()
    payload = {
        "type": node_type,
        "label": label,
        "metadata": metadata,
        "source_url": source_url,
    }

    try:
        result = client.table("nodes").insert(payload).execute()
    except Exception as exc:
        log_error(f"Node insert failed for label '{label}': {exc}")
        raise RuntimeError(f"Failed to insert node '{label}' into nodes table: {exc}") from exc

    rows = result.data or []
    if not rows or not rows[0].get("id"):
        raise RuntimeError("Node insert succeeded but did not return an id.")

    return str(rows[0]["id"])


def _get_or_create_node(node_type: str, label: str, metadata: dict[str, Any] | None = None) -> str:
    client = _get_supabase_client()
    clean_label = _clean_text(label)
    if not clean_label:
        raise ValueError(f"Cannot create or lookup {node_type} node with empty label.")

    try:
        existing = (
            client.table("nodes")
            .select("id")
            .eq("type", node_type)
            .eq("label", clean_label)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        log_error(f"Node lookup failed for type '{node_type}' label '{clean_label}': {exc}")
        raise RuntimeError(f"Failed to query existing {node_type} node '{clean_label}': {exc}") from exc

    rows = existing.data or []
    if rows:
        return str(rows[0]["id"])

    return _insert_node_row(node_type=node_type, label=clean_label, metadata=metadata or {}, source_url="")


def _insert_edge_if_missing(from_node_id: str, to_node_id: str, relation: str) -> None:
    client = _get_supabase_client()
    payload = {
        "from_node_id": from_node_id,
        "to_node_id": to_node_id,
        "relation": relation,
    }

    try:
        client.table("edges").upsert(payload, on_conflict="from_node_id,to_node_id,relation").execute()
    except Exception as exc:
        log_error(f"Edge insert failed for relation '{relation}': {exc}")
        raise RuntimeError(f"Failed inserting edge relation '{relation}': {exc}") from exc


def insert_node(
    data: dict,
    source_url: str,
    event_type: str = "decision",
    metadata_extra: dict[str, Any] | None = None,
) -> str:
    if not isinstance(data, dict):
        raise ValueError("insert_node expected data to be a dict.")

    decision = _clean_text(data.get("decision"))
    reason = _clean_text(data.get("reason"))
    risk = _clean_text(data.get("risk")) or "unknown"

    raw_services = data.get("services", [])
    if isinstance(raw_services, list):
        services = [_clean_text(service) for service in raw_services if _clean_text(service)]
    elif isinstance(raw_services, str):
        services = [_clean_text(raw_services)] if _clean_text(raw_services) else []
    else:
        services = []

    if not decision:
        raise ValueError("insert_node requires a non-empty 'decision'.")

    metadata = {
        "reason": reason,
        "services": services,
        "risk": risk,
        "event": _clean_text(event_type) or "decision",
    }
    if isinstance(metadata_extra, dict):
        metadata.update(metadata_extra)

    return _insert_node_row(
        node_type="decision",
        label=decision,
        metadata=metadata,
        source_url=_clean_text(source_url),
    )


def insert_lightweight_event(
    event_type: str,
    label: str,
    source_url: str,
    metadata: dict[str, Any] | None = None,
) -> str:
    clean_event_type = _clean_text(event_type) or "event"
    clean_label = _clean_text(label)
    if not clean_label:
        raise ValueError("insert_lightweight_event requires a non-empty label.")

    final_metadata: dict[str, Any] = {"event": clean_event_type}
    if isinstance(metadata, dict):
        final_metadata.update(metadata)

    return _insert_node_row(
        node_type="event",
        label=clean_label,
        metadata=final_metadata,
        source_url=_clean_text(source_url),
    )


def node_exists(source_url: str, label: str, event_type: str | None = None) -> bool:
    client = _get_supabase_client()
    clean_source_url = _clean_text(source_url)
    clean_label = _clean_text(label)
    if not clean_source_url or not clean_label:
        return False

    try:
        result = (
            client.table("nodes")
            .select("id,metadata")
            .eq("source_url", clean_source_url)
            .eq("label", clean_label)
            .limit(20)
            .execute()
        )
    except Exception as exc:
        log_error(f"Node duplicate lookup failed for source_url '{clean_source_url}': {exc}")
        raise RuntimeError(f"Failed to check duplicate node for source_url '{clean_source_url}': {exc}") from exc

    rows = result.data or []
    if not rows:
        return False
    if not event_type:
        return True

    clean_event = _clean_text(event_type)
    for row in rows:
        metadata = row.get("metadata") or {}
        if isinstance(metadata, dict):
            existing_event = _clean_text(metadata.get("event") or metadata.get("event_type"))
            if existing_event == clean_event:
                return True
    return False


def get_graph_stats() -> dict[str, Any]:
    client = _get_supabase_client()

    def _count(table_name: str) -> int:
        try:
            result = client.table(table_name).select("*", count="exact", head=True).execute()
        except Exception as exc:
            log_error(f"Stats count failed for table '{table_name}': {exc}")
            raise RuntimeError(f"Failed counting table '{table_name}': {exc}") from exc
        return int(result.count or 0)

    last_event = "none"
    try:
        recent = (
            client.table("nodes")
            .select("metadata")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        recent_rows = recent.data or []
        if recent_rows:
            metadata = recent_rows[0].get("metadata") or {}
            if isinstance(metadata, dict):
                last_event = _clean_text(metadata.get("event") or metadata.get("event_type")) or "none"
    except Exception as exc:
        log_error(f"Stats lookup for last_event failed: {exc}")
        raise RuntimeError(f"Failed loading last_event: {exc}") from exc

    return {
        "nodes": _count("nodes"),
        "edges": _count("edges"),
        "embeddings": _count("node_embeddings"),
        "last_event": last_event,
    }


def insert_embedding(node_id: str, chunk: str, embedding: list[float]) -> None:
    client = _get_supabase_client()
    clean_node_id = _clean_text(node_id)
    clean_chunk = _clean_text(chunk)

    if not clean_node_id:
        raise ValueError("insert_embedding requires a non-empty node_id.")
    if not clean_chunk:
        raise ValueError("insert_embedding requires a non-empty chunk.")
    if not isinstance(embedding, list) or not embedding:
        raise ValueError("insert_embedding requires a non-empty embedding list.")

    try:
        vector = [float(value) for value in embedding]
    except (TypeError, ValueError) as exc:
        raise ValueError("insert_embedding received non-numeric embedding values.") from exc

    payload = {"node_id": clean_node_id, "chunk": clean_chunk, "embedding": vector}

    try:
        client.table("node_embeddings").insert(payload).execute()
    except Exception as exc:
        log_error(f"Embedding insert failed for node {clean_node_id}: {exc}")
        raise RuntimeError(f"Failed to insert embedding for node {clean_node_id}: {exc}") from exc


def insert_edges(node_id: str, repo: str, author: str, services: list[str]) -> None:
    clean_node_id = _clean_text(node_id)
    if not clean_node_id:
        raise ValueError("insert_edges requires a non-empty node_id.")

    repo_name = _clean_text(repo)
    author_name = _clean_text(author)
    service_names = [_clean_text(service) for service in (services or []) if _clean_text(service)]

    if repo_name:
        repo_node_id = _get_or_create_node("repo", repo_name)
        _insert_edge_if_missing(clean_node_id, repo_node_id, "belongs_to_repo")

    if author_name:
        author_node_id = _get_or_create_node("author", author_name)
        _insert_edge_if_missing(clean_node_id, author_node_id, "owned_by_author")

    for service_name in service_names:
        service_node_id = _get_or_create_node("service", service_name)
        _insert_edge_if_missing(clean_node_id, service_node_id, "affects_service")
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
