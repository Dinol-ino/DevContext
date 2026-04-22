import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from supabase import Client, create_client

try:
    from .utils import log_error
except ImportError:
    from utils import log_error


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
    try:
        existing = (
            client.table("edges")
            .select("from_node_id")
            .eq("from_node_id", from_node_id)
            .eq("to_node_id", to_node_id)
            .eq("relation", relation)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        log_error(f"Edge lookup failed ({from_node_id} -> {to_node_id}, {relation}): {exc}")
        raise RuntimeError(
            f"Failed checking existing edge ({from_node_id} -> {to_node_id}, {relation}): {exc}"
        ) from exc

    if existing.data:
        return

    payload = {
        "from_node_id": from_node_id,
        "to_node_id": to_node_id,
        "relation": relation,
    }

    try:
        client.table("edges").insert(payload).execute()
    except Exception as exc:
        log_error(f"Edge insert failed for relation '{relation}': {exc}")
        raise RuntimeError(f"Failed inserting edge relation '{relation}': {exc}") from exc


def insert_node(data: dict, source_url: str) -> str:
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

    metadata = {"reason": reason, "services": services, "risk": risk}
    return _insert_node_row(
        node_type="decision",
        label=decision,
        metadata=metadata,
        source_url=_clean_text(source_url),
    )


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
