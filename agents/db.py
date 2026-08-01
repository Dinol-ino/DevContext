from __future__ import annotations

import json
import logging
import math
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID

from dotenv import load_dotenv
from supabase import Client, create_client

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=ENV_FILE, override=False)

logger = logging.getLogger("devcontextiq.db")


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(_clean_text(item) for item in value if _clean_text(item))
    if isinstance(value, dict):
        return " ".join(_clean_text(item) for item in value.values() if _clean_text(item))
    return _clean_text(value)


def _normalize_uuid(value: Any) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    try:
        return str(UUID(text))
    except (TypeError, ValueError):
        return None


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", _clean_text(text).lower()))


def _metadata(row: dict[str, Any]) -> dict[str, Any]:
    metadata = row.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def _parse_embedding(raw_value: Any) -> list[float]:
    if isinstance(raw_value, list):
        try:
            return [float(value) for value in raw_value]
        except (TypeError, ValueError):
            return []

    if isinstance(raw_value, str):
        try:
            loaded = json.loads(raw_value)
        except (TypeError, ValueError):
            return []
        if isinstance(loaded, list):
            try:
                return [float(value) for value in loaded]
            except (TypeError, ValueError):
                return []

    return []


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0

    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


def _resolve_supabase_key() -> str:
    return _clean_text(os.getenv("SUPABASE_KEY")) or _clean_text(os.getenv("SUPABASE_SERVICE_ROLE_KEY"))


@lru_cache(maxsize=1)
def get_client() -> Client | None:
    url = _clean_text(os.getenv("SUPABASE_URL"))
    key = _resolve_supabase_key()
    if not url or not key:
        return None
    try:
        import httpx
        from supabase import ClientOptions
        timeout = httpx.Timeout(connect=4.0, read=8.0, write=8.0, pool=4.0)
        http_client = httpx.Client(timeout=timeout)
        return create_client(url, key, options=ClientOptions(httpx_client=http_client, postgrest_client_timeout=8))
    except Exception:
        return None



def get_supabase_client() -> Client | None:
    return get_client()


def _repo_filter_rows(rows: list[dict[str, Any]], repo_id: str | None) -> list[dict[str, Any]]:
    """Filter rows to those belonging to a given repo_id (owner/name format).

    Matches against:
      - node label (for repo nodes)
      - metadata.repo
      - metadata.owner + '/' + metadata.name
    When repo_id is None or empty, returns all rows unchanged.
    """
    clean_repo = _clean_text(repo_id).lower() if repo_id else ""
    if not clean_repo:
        return rows

    filtered: list[dict[str, Any]] = []
    for row in rows:
        label = _clean_text(row.get("label")).lower()
        meta = _metadata(row)
        meta_repo = _clean_text(meta.get("repo")).lower()
        meta_owner = _clean_text(meta.get("owner")).lower()
        meta_name = _clean_text(meta.get("name")).lower()
        composite = f"{meta_owner}/{meta_name}" if meta_owner and meta_name else ""

        if (
            clean_repo == label
            or clean_repo == meta_repo
            or clean_repo == composite
            or clean_repo in label
            or clean_repo in meta_repo
        ):
            filtered.append(row)
    return filtered


def health_check() -> bool:
    client = get_client()
    if client is None:
        return False
    try:
        client.table("nodes").select("id").limit(1).execute()
        return True
    except Exception:
        return False


def _safe_select(table_name: str, columns: str = "*", limit: int = 200) -> list[dict[str, Any]]:
    client = get_client()
    if client is None:
        return []
    try:
        response = client.table(table_name).select(columns).limit(max(1, min(limit, 500))).execute()
    except Exception:
        return []
    return response.data or []


def fetch_recent_nodes(limit: int = 20, repo_id: str | None = None) -> list[dict[str, Any]]:
    client = get_client()
    if client is None:
        return []

    # Fetch more rows when filtering so we still get enough after the filter
    fetch_limit = max(1, min(limit * 3 if repo_id else limit, 500))
    try:
        response = client.table("nodes").select("*").order("created_at", desc=True).limit(fetch_limit).execute()
        rows = response.data or []
    except Exception:
        rows = _safe_select("nodes", limit=fetch_limit)

    rows = _repo_filter_rows(rows, repo_id)
    return rows[:max(1, limit)]


def fetch_nodes(limit: int = 200, repo_id: str | None = None) -> list[dict[str, Any]]:
    return fetch_recent_nodes(limit=limit, repo_id=repo_id)


def search_nodes_text(query: str, limit: int = 10, repo_id: str | None = None) -> list[dict[str, Any]]:
    query_text = _clean_text(query)
    if not query_text:
        return []

    query_terms = _tokenize(query_text)
    rows = fetch_recent_nodes(limit=300, repo_id=repo_id)
    scored: list[tuple[float, dict[str, Any]]] = []

    for row in rows:
        metadata = _metadata(row)
        label = _normalize_value(row.get("label"))
        node_type = _normalize_value(row.get("type"))
        reason = _normalize_value(metadata.get("reason"))
        services = _normalize_value(metadata.get("services"))
        source_url = _normalize_value(row.get("source_url"))
        haystack = " ".join(part for part in [label, node_type, reason, services, source_url] if part)
        haystack_lower = haystack.lower()
        row_terms = _tokenize(haystack)
        overlap = query_terms.intersection(row_terms)
        if not overlap:
            continue

        score = float(len(overlap))
        if label and label.lower() in query_text.lower():
            score += 5.0
        if query_text.lower() in haystack_lower:
            score += 3.0
        if node_type and node_type.lower() in query_text.lower():
            score += 1.5
        if services:
            score += min(2.0, len(query_terms.intersection(_tokenize(services))) * 0.75)

        enriched = dict(row)
        enriched["_score"] = round(score, 4)
        scored.append((score, enriched))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [row for _, row in scored[: max(1, limit)]]


def fetch_related_edges(node_ids: list[str]) -> list[dict[str, Any]]:
    client = get_client()
    clean_ids = [_clean_text(node_id) for node_id in node_ids if _clean_text(node_id)]
    if client is None or not clean_ids:
        return []

    collected: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    try:
        for field_name in ("from_node_id", "to_node_id"):
            response = client.table("edges").select("*").in_(field_name, clean_ids).limit(300).execute()
            for row in response.data or []:
                key = (
                    _clean_text(row.get("from_node_id")),
                    _clean_text(row.get("to_node_id")),
                    _clean_text(row.get("relation")),
                )
                if key not in seen:
                    seen.add(key)
                    collected.append(row)
    except Exception:
        return []

    return collected


def _fetch_nodes_by_ids(node_ids: list[str]) -> dict[str, dict[str, Any]]:
    client = get_client()
    clean_ids = [_clean_text(node_id) for node_id in node_ids if _clean_text(node_id)]
    if client is None or not clean_ids:
        return {}

    try:
        response = client.table("nodes").select("*").in_("id", clean_ids).limit(len(clean_ids)).execute()
    except Exception:
        return {}

    return {_clean_text(row.get("id")): row for row in (response.data or []) if _clean_text(row.get("id"))}


def _embedding_select_columns(include_metadata: bool = True) -> str:
    if include_metadata:
        return "id,node_id,chunk,embedding,repo_id,file_path,language,start_line,end_line,content_hash"
    return "node_id,chunk,embedding"


def _fallback_enabled() -> bool:
    return _clean_text(os.getenv("RAG_ENABLE_BRUTE_FORCE_FALLBACK")).lower() in {"1", "true", "yes", "on"}


def _fallback_page_size() -> int:
    try:
        return max(1, int(_clean_text(os.getenv("RAG_BRUTE_FORCE_PAGE_SIZE")) or "500"))
    except ValueError:
        return 500


def _fallback_max_rows() -> int:
    try:
        return max(1, int(_clean_text(os.getenv("RAG_BRUTE_FORCE_MAX_ROWS")) or "5000"))
    except ValueError:
        return 5000


def _row_matches_repo(row: dict[str, Any], node: dict[str, Any], repo_id: str | None) -> bool:
    clean_repo = _clean_text(repo_id)
    if not clean_repo:
        return True

    row_repo = _clean_text(row.get("repo_id"))
    if row_repo and row_repo == clean_repo:
        return True

    metadata = _metadata(node)
    owner = _clean_text(metadata.get("owner"))
    name = _clean_text(metadata.get("name"))
    return clean_repo in {
        _clean_text(node.get("id")),
        _clean_text(node.get("label")),
        _clean_text(metadata.get("repo")),
        f"{owner}/{name}" if owner and name else "",
    }


def _merge_embedding_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    node_ids = [_clean_text(row.get("node_id")) for row in rows if _clean_text(row.get("node_id"))]
    node_map = _fetch_nodes_by_ids(list(dict.fromkeys(node_ids)))

    merged: list[dict[str, Any]] = []
    for row in rows:
        node_id = _clean_text(row.get("node_id"))
        similarity = float(row.get("similarity", row.get("_vector_score", 0.0)) or 0.0)
        if similarity <= 0:
            continue

        node = dict(node_map.get(node_id, {}))
        chunk_id = _clean_text(row.get("id"))
        node["node_id"] = node_id
        node["chunk_id"] = chunk_id
        node["embedding_id"] = chunk_id
        node["chunk"] = row.get("chunk")
        node["repo_id"] = row.get("repo_id")
        node["file_path"] = row.get("file_path")
        node["language"] = row.get("language")
        node["start_line"] = row.get("start_line")
        node["end_line"] = row.get("end_line")
        node["content_hash"] = row.get("content_hash")
        node["_vector_score"] = round(similarity, 4)
        if not node.get("id"):
            node["id"] = node_id
        merged.append(node)

    return merged


def _fetch_embedding_rows_for_fallback(client: Client) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    page_size = _fallback_page_size()
    max_rows = _fallback_max_rows()
    start = 0
    include_metadata = True

    while start < max_rows:
        end = min(start + page_size - 1, max_rows - 1)
        try:
            response = (
                client.table("node_embeddings")
                .select(_embedding_select_columns(include_metadata=include_metadata))
                .range(start, end)
                .execute()
            )
        except Exception as exc:
            if include_metadata:
                logger.warning("node_embeddings metadata select failed; retrying legacy select: %s", exc)
                include_metadata = False
                continue
            logger.error("node_embeddings fallback select failed: %s", exc)
            return rows

        page_rows = response.data or []
        rows.extend(page_rows)
        if len(page_rows) < page_size:
            break
        start += page_size

    if len(rows) >= max_rows:
        logger.warning("Brute-force embedding fallback reached RAG_BRUTE_FORCE_MAX_ROWS=%s; results may be incomplete", max_rows)

    return rows


def fetch_embedding_matches(query_embedding: list[float], limit: int = 5, repo_id: str | None = None) -> list[dict[str, Any]]:
    clean_query = _parse_embedding(query_embedding)
    if not clean_query:
        return []

    client = get_client()
    if client is None:
        return []

    try:
        rpc_params: dict[str, Any] = {
            "query_embedding": clean_query,
            "match_limit": max(1, limit),
        }
        if repo_id and _clean_text(repo_id):
            rpc_params["filter_repo_id"] = _clean_text(repo_id)

        response = client.rpc("match_embeddings", rpc_params).execute()
        return _merge_embedding_rows(response.data or [])
    except Exception as exc:
        logger.error("match_embeddings RPC failed; semantic search degraded until migration is applied: %s", exc)
        if not _fallback_enabled():
            return []

    rows = _fetch_embedding_rows_for_fallback(client)
    if not rows:
        return []

    candidates: list[tuple[float, dict[str, Any]]] = []
    for row in rows:
        if repo_id and _clean_text(row.get("repo_id")) and _clean_text(row.get("repo_id")) != _clean_text(repo_id):
            continue

        stored_vector = _parse_embedding(row.get("embedding"))
        if not stored_vector or len(stored_vector) != len(clean_query):
            continue

        similarity = _cosine_similarity(clean_query, stored_vector)
        if similarity <= 0:
            continue

        enriched = dict(row)
        enriched["_vector_score"] = round(similarity, 4)
        candidates.append((similarity, enriched))

    if not candidates:
        return []

    if repo_id:
        node_map = _fetch_nodes_by_ids(list(dict.fromkeys(_clean_text(row.get("node_id")) for _, row in candidates)))
        candidates = [
            (score, row)
            for score, row in candidates
            if _row_matches_repo(row, node_map.get(_clean_text(row.get("node_id")), {}), repo_id)
        ]

    candidates.sort(key=lambda item: item[0], reverse=True)
    top_rows = [row for _, row in candidates[: max(1, limit)]]
    return _merge_embedding_rows(top_rows)


def fetch_decisions(limit: int = 200, repo_id: str | None = None) -> list[dict[str, Any]]:
    return [row for row in fetch_recent_nodes(limit=limit, repo_id=repo_id) if _clean_text(row.get("type")).lower() == "decision"]


def fetch_services(limit: int = 200, repo_id: str | None = None) -> list[dict[str, Any]]:
    services: list[dict[str, Any]] = []
    seen: set[str] = set()

    for row in fetch_decisions(limit=limit, repo_id=repo_id):
        for service in _metadata(row).get("services", []):
            name = _clean_text(service)
            if name and name not in seen:
                seen.add(name)
                services.append({"name": name, "source_node_id": row.get("id")})

    return services


def fetch_incidents(limit: int = 200, repo_id: str | None = None) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for row in fetch_recent_nodes(limit=limit, repo_id=repo_id):
        row_type = _clean_text(row.get("type")).lower()
        label = _clean_text(row.get("label")).lower()
        metadata_text = _normalize_value(_metadata(row)).lower()
        if (
            row_type == "incident"
            or "incident" in label
            or "alert" in label
            or "outage" in label
            or "incident" in metadata_text
        ):
            results.append(row)
    return results


def log_user_auth_event(
    *,
    event_type: str,
    email: str,
    user_id: str | None = None,
    provider: str = "email",
    source: str = "frontend",
    ip_address: str | None = None,
    user_agent: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    client = get_client()
    if client is None:
        raise RuntimeError("Supabase is not configured on the backend.")

    clean_event_type = _clean_text(event_type).lower()
    if clean_event_type not in {"register", "login"}:
        raise ValueError("event_type must be either 'register' or 'login'.")

    clean_email = _clean_text(email).lower()
    if not clean_email:
        raise ValueError("email is required.")

    payload = {
        "user_id": _normalize_uuid(user_id),
        "email": clean_email,
        "auth_event": clean_event_type,
        "auth_provider": _clean_text(provider) or "email",
        "auth_source": _clean_text(source) or "frontend",
        "ip_address": _clean_text(ip_address) or None,
        "user_agent": _clean_text(user_agent) or None,
        "metadata": metadata if isinstance(metadata, dict) else {},
    }

    try:
        response = client.table("user_auth_events").insert(payload).execute()
    except Exception as exc:
        raise RuntimeError(f"Failed to insert auth event: {exc}") from exc

    data = response.data or []
    if data:
        return data[0]
    return payload


# --- Graph Insertion Functions ---

def _insert_node_row(node_type: str, label: str, metadata: dict[str, Any], source_url: str = "") -> str:
    client = get_client()
    if client is None:
        raise RuntimeError("Database client is not initialized.")

    payload = {
        "type": _clean_text(node_type) or "decision",
        "label": _clean_text(label),
        "metadata": metadata if isinstance(metadata, dict) else {},
        "source_url": _clean_text(source_url),
    }
    result = client.table("nodes").insert(payload).execute()
    rows = result.data or []
    if not rows or not rows[0].get("id"):
        raise RuntimeError("Node insert did not return an id.")
    return str(rows[0]["id"])


def _get_or_create_node(node_type: str, label: str, metadata: dict[str, Any] | None = None) -> str:
    client = get_client()
    clean_label = _clean_text(label)
    if not clean_label:
        raise ValueError(f"Cannot create or lookup {node_type} node with empty label.")

    if client:
        try:
            result = (
                client.table("nodes")
                .select("id")
                .eq("type", _clean_text(node_type))
                .eq("label", clean_label)
                .limit(1)
                .execute()
            )
            rows = result.data or []
            if rows:
                return str(rows[0]["id"])
        except Exception:
            pass

    return _insert_node_row(_clean_text(node_type), clean_label, metadata or {}, "")


def _insert_edge_if_missing(from_node_id: str, to_node_id: str, relation: str) -> None:
    client = get_client()
    if client is None:
        return

    payload = {
        "from_node_id": _clean_text(from_node_id),
        "to_node_id": _clean_text(to_node_id),
        "relation": _clean_text(relation),
    }
    try:
        client.table("edges").upsert(payload, on_conflict="from_node_id,to_node_id,relation").execute()
    except Exception:
        pass


# --- Chat Memory Functions ---

def create_chat_thread(user_id: str | None = None, repo_id: str | None = None, title: str = "New Conversation") -> dict[str, Any]:
    client = get_client()
    if client is None:
        raise RuntimeError("Supabase client is not initialized.")

    payload = {
        "user_id": _normalize_uuid(user_id),
        "repo_id": _clean_text(repo_id) or None,
        "title": _clean_text(title) or "New Conversation",
    }
    response = client.table("chat_threads").insert(payload).execute()
    rows = response.data or []
    if not rows:
        raise RuntimeError("Failed to create chat thread.")
    return rows[0]


def list_chat_threads(user_id: str | None = None, repo_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    client = get_client()
    if client is None:
        return []

    query = client.table("chat_threads").select("*").order("updated_at", desc=True).limit(max(1, min(limit, 100)))
    clean_user_id = _normalize_uuid(user_id)
    if clean_user_id:
        query = query.eq("user_id", clean_user_id)
    clean_repo_id = _clean_text(repo_id)
    if clean_repo_id:
        query = query.eq("repo_id", clean_repo_id)

    try:
        response = query.execute()
        return response.data or []
    except Exception:
        return []


def get_chat_thread(thread_id: str) -> dict[str, Any] | None:
    client = get_client()
    if client is None:
        return None

    clean_id = _normalize_uuid(thread_id)
    if not clean_id:
        return None

    try:
        response = client.table("chat_threads").select("*").eq("id", clean_id).limit(1).execute()
        rows = response.data or []
        return rows[0] if rows else None
    except Exception:
        return None


def delete_chat_thread(thread_id: str) -> bool:
    client = get_client()
    if client is None:
        return False

    clean_id = _normalize_uuid(thread_id)
    if not clean_id:
        return False

    try:
        response = client.table("chat_threads").delete().eq("id", clean_id).execute()
        return bool(response.data)
    except Exception:
        return False


def add_chat_message(
    thread_id: str,
    role: str,
    content: str,
    confidence: float | None = None,
    sources: list[dict[str, Any]] | None = None,
    used_model: str | None = None,
) -> dict[str, Any]:
    client = get_client()
    if client is None:
        raise RuntimeError("Supabase client is not initialized.")

    clean_thread_id = _normalize_uuid(thread_id)
    if not clean_thread_id:
        raise ValueError("Valid thread_id is required.")

    clean_role = _clean_text(role).lower()
    if clean_role not in {"user", "assistant"}:
        raise ValueError("Role must be 'user' or 'assistant'.")

    payload = {
        "thread_id": clean_thread_id,
        "role": clean_role,
        "content": _clean_text(content),
        "confidence": float(confidence) if confidence is not None else None,
        "sources": sources if isinstance(sources, list) else [],
        "used_model": _clean_text(used_model) or None,
    }

    response = client.table("chat_messages").insert(payload).execute()
    rows = response.data or []
    if not rows:
        raise RuntimeError("Failed to insert chat message.")

    # Update thread updated_at
    from datetime import datetime, timezone
    try:
        client.table("chat_threads").update({"updated_at": datetime.now(timezone.utc).isoformat()}).eq("id", clean_thread_id).execute()
    except Exception:
        pass

    return rows[0]


def fetch_chat_messages(thread_id: str, limit: int = 100) -> list[dict[str, Any]]:
    client = get_client()
    if client is None:
        return []

    clean_thread_id = _normalize_uuid(thread_id)
    if not clean_thread_id:
        return []

    try:
        response = (
            client.table("chat_messages")
            .select("*")
            .eq("thread_id", clean_thread_id)
            .order("created_at", asc=True)
            .limit(max(1, min(limit, 200)))
            .execute()
        )
        return response.data or []
    except Exception:
        return []

