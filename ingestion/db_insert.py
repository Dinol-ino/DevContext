from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from supabase import Client, create_client

from .utils import clean_text, log_error, log_warning

BASE_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = BASE_DIR / ".env"


def _load_env() -> None:
    load_dotenv(dotenv_path=ENV_PATH, override=False)


def _clean_list(values: Any) -> list[str]:
    if isinstance(values, list):
        return [clean_text(value) for value in values if clean_text(value)]
    if isinstance(values, str):
        value = clean_text(values)
        return [value] if value else []
    return []


def _resolve_supabase_key() -> str:
    return clean_text(os.getenv("SUPABASE_KEY")) or clean_text(os.getenv("SUPABASE_SERVICE_ROLE_KEY"))


@lru_cache(maxsize=1)
def _get_supabase_client() -> Client:
    _load_env()
    url = clean_text(os.getenv("SUPABASE_URL"))
    key = _resolve_supabase_key()

    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be configured.")

    try:
        return create_client(url, key)
    except Exception as exc:
        log_error(f"Supabase client initialization failed: {exc}")
        raise RuntimeError(f"Failed to initialize Supabase client: {exc}") from exc


def _insert_node_row(node_type: str, label: str, metadata: dict[str, Any], source_url: str = "") -> str:
    client = _get_supabase_client()
    payload = {
        "type": clean_text(node_type) or "decision",
        "label": clean_text(label),
        "metadata": metadata if isinstance(metadata, dict) else {},
        "source_url": clean_text(source_url),
    }

    try:
        result = client.table("nodes").insert(payload).execute()
    except Exception as exc:
        log_error(f"Node insert failed for label '{payload['label']}': {exc}")
        raise RuntimeError(f"Failed to insert node '{payload['label']}': {exc}") from exc

    rows = result.data or []
    if not rows or not rows[0].get("id"):
        raise RuntimeError("Node insert did not return an id.")
    return str(rows[0]["id"])


def _get_or_create_node(node_type: str, label: str, metadata: dict[str, Any] | None = None) -> str:
    client = _get_supabase_client()
    clean_label = clean_text(label)
    if not clean_label:
        raise ValueError(f"Cannot create or lookup {node_type} node with empty label.")

    try:
        result = (
            client.table("nodes")
            .select("id")
            .eq("type", clean_text(node_type))
            .eq("label", clean_label)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        log_error(f"Node lookup failed for type '{node_type}' label '{clean_label}': {exc}")
        raise RuntimeError(f"Failed to query existing {node_type} node '{clean_label}': {exc}") from exc

    rows = result.data or []
    if rows:
        return str(rows[0]["id"])

    return _insert_node_row(clean_text(node_type), clean_label, metadata or {}, "")


def _insert_edge_if_missing(from_node_id: str, to_node_id: str, relation: str) -> None:
    client = _get_supabase_client()
    payload = {
        "from_node_id": clean_text(from_node_id),
        "to_node_id": clean_text(to_node_id),
        "relation": clean_text(relation),
    }

    try:
        client.table("edges").upsert(payload, on_conflict="from_node_id,to_node_id,relation").execute()
    except Exception as exc:
        log_error(f"Edge insert failed for relation '{payload['relation']}': {exc}")
        raise RuntimeError(f"Failed inserting edge relation '{payload['relation']}': {exc}") from exc


def insert_node(
    data: dict[str, Any],
    source_url: str,
    event_type: str = "decision",
    metadata_extra: dict[str, Any] | None = None,
) -> str:
    if not isinstance(data, dict):
        raise ValueError("insert_node expected data to be a dict.")

    decision = clean_text(data.get("decision") or data.get("label"))
    reason = clean_text(data.get("reason"))
    risk = clean_text(data.get("risk")) or "unknown"
    services = _clean_list(data.get("services"))

    if not decision:
        raise ValueError("insert_node requires a non-empty 'decision'.")

    metadata: dict[str, Any] = {
        "reason": reason,
        "services": services,
        "risk": risk,
        "event": clean_text(event_type) or "decision",
    }
    if isinstance(metadata_extra, dict):
        metadata.update(metadata_extra)

    return _insert_node_row("decision", decision, metadata, source_url)


def insert_lightweight_event(
    event_type: str,
    label: str,
    source_url: str,
    metadata: dict[str, Any] | None = None,
) -> str:
    clean_label = clean_text(label)
    if not clean_label:
        raise ValueError("insert_lightweight_event requires a non-empty label.")

    payload_metadata: dict[str, Any] = {"event": clean_text(event_type) or "event"}
    if isinstance(metadata, dict):
        payload_metadata.update(metadata)

    return _insert_node_row("event", clean_label, payload_metadata, source_url)


def insert_adr_node(
    title: str,
    summary: str,
    path: str,
    repo: str,
    author: str,
    source_url: str,
    metadata_extra: dict[str, Any] | None = None,
) -> str:
    clean_title = clean_text(title)
    if not clean_title:
        raise ValueError("insert_adr_node requires a non-empty title.")

    metadata: dict[str, Any] = {
        "title": clean_title,
        "summary": clean_text(summary),
        "path": clean_text(path),
        "repo": clean_text(repo),
        "author": clean_text(author),
        "event": "adr",
    }
    if isinstance(metadata_extra, dict):
        metadata.update(metadata_extra)

    return _insert_node_row("adr", clean_title, metadata, source_url)


def insert_adr_edges(adr_node_id: str, repo: str, author: str) -> None:
    clean_adr_node_id = clean_text(adr_node_id)
    if not clean_adr_node_id:
        raise ValueError("insert_adr_edges requires a non-empty adr_node_id.")

    repo_name = clean_text(repo)
    author_name = clean_text(author)

    if repo_name:
        repo_node_id = _get_or_create_node("repo", repo_name)
        _insert_edge_if_missing(repo_node_id, clean_adr_node_id, "contains_adr")

    if author_name:
        author_node_id = _get_or_create_node("author", author_name)
        _insert_edge_if_missing(author_node_id, clean_adr_node_id, "authored_adr")


def node_exists(source_url: str, label: str, event_type: str | None = None) -> bool:
    client = _get_supabase_client()
    clean_source_url = clean_text(source_url)
    clean_label = clean_text(label)
    clean_event = clean_text(event_type)

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
    if not clean_event:
        return True

    for row in rows:
        metadata = row.get("metadata") or {}
        if isinstance(metadata, dict):
            existing_event = clean_text(metadata.get("event") or metadata.get("event_type"))
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
        recent = client.table("nodes").select("metadata").order("created_at", desc=True).limit(1).execute()
        rows = recent.data or []
        if rows:
            metadata = rows[0].get("metadata") or {}
            if isinstance(metadata, dict):
                last_event = clean_text(metadata.get("event") or metadata.get("event_type")) or "none"
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
    clean_node_id = clean_text(node_id)
    clean_chunk = clean_text(chunk)

    if not clean_node_id or not clean_chunk:
        raise ValueError("insert_embedding requires non-empty node_id and chunk.")

    if not isinstance(embedding, list) or not embedding:
        log_warning(f"Embedding skipped for node_id={clean_node_id}")
        return

    try:
        vector = [float(value) for value in embedding]
    except (TypeError, ValueError):
        log_warning(f"Embedding skipped for node_id={clean_node_id} due to invalid values")
        return

    try:
        _get_supabase_client().table("node_embeddings").insert(
            {"node_id": clean_node_id, "chunk": clean_chunk, "embedding": vector}
        ).execute()
    except Exception as exc:
        log_warning(f"Embedding insert failed for node_id={clean_node_id}: {exc}")


def insert_edges(node_id: str, repo: str, author: str, services: list[str]) -> None:
    clean_node_id = clean_text(node_id)
    if not clean_node_id:
        raise ValueError("insert_edges requires a non-empty node_id.")

    repo_name = clean_text(repo)
    author_name = clean_text(author)
    service_names = _clean_list(services)

    if repo_name:
        repo_node_id = _get_or_create_node("repo", repo_name)
        _insert_edge_if_missing(clean_node_id, repo_node_id, "belongs_to_repo")

    if author_name:
        author_node_id = _get_or_create_node("author", author_name)
        _insert_edge_if_missing(clean_node_id, author_node_id, "owned_by_author")

    for service_name in service_names:
        service_node_id = _get_or_create_node("service", service_name)
        _insert_edge_if_missing(clean_node_id, service_node_id, "affects_service")


def insert_decision(data: dict[str, Any], source_url: str = "") -> dict[str, Any]:
    try:
        node_id = insert_node(data=data, source_url=source_url, event_type="decision")
        return {"success": True, "node_id": node_id}
    except Exception as exc:
        return {"success": False, "error": str(exc)}
