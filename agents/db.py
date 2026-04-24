from __future__ import annotations

import json
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
        return create_client(url, key)
    except Exception:
        return None


def get_supabase_client() -> Client | None:
    return get_client()


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


def fetch_recent_nodes(limit: int = 20) -> list[dict[str, Any]]:
    client = get_client()
    if client is None:
        return []

    capped_limit = max(1, min(limit, 300))
    try:
        response = client.table("nodes").select("*").order("created_at", desc=True).limit(capped_limit).execute()
        return response.data or []
    except Exception:
        return _safe_select("nodes", limit=capped_limit)


def fetch_nodes(limit: int = 200) -> list[dict[str, Any]]:
    return fetch_recent_nodes(limit=limit)


def search_nodes_text(query: str, limit: int = 10) -> list[dict[str, Any]]:
    query_text = _clean_text(query)
    if not query_text:
        return []

    query_terms = _tokenize(query_text)
    rows = fetch_recent_nodes(limit=300)
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


def fetch_embedding_matches(query_embedding: list[float], limit: int = 5) -> list[dict[str, Any]]:
    clean_query = _parse_embedding(query_embedding)
    if not clean_query:
        return []

    client = get_client()
    if client is None:
        return []

    try:
        response = client.table("node_embeddings").select("node_id,chunk,embedding").limit(250).execute()
    except Exception:
        return []

    candidates: list[tuple[float, dict[str, Any]]] = []
    for row in response.data or []:
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

    candidates.sort(key=lambda item: item[0], reverse=True)
    top_rows = [row for _, row in candidates[: max(1, limit)]]
    node_map = _fetch_nodes_by_ids([_clean_text(row.get("node_id")) for row in top_rows])

    merged: list[dict[str, Any]] = []
    for row in top_rows:
        node_id = _clean_text(row.get("node_id"))
        node = dict(node_map.get(node_id, {}))
        node["node_id"] = node_id
        node["chunk"] = row.get("chunk")
        node["_vector_score"] = row.get("_vector_score", 0.0)
        if not node.get("id"):
            node["id"] = node_id
        merged.append(node)

    return merged


def fetch_decisions(limit: int = 200) -> list[dict[str, Any]]:
    return [row for row in fetch_recent_nodes(limit=limit) if _clean_text(row.get("type")).lower() == "decision"]


def fetch_services(limit: int = 200) -> list[dict[str, Any]]:
    services: list[dict[str, Any]] = []
    seen: set[str] = set()

    for row in fetch_decisions(limit=limit):
        for service in _metadata(row).get("services", []):
            name = _clean_text(service)
            if name and name not in seen:
                seen.add(name)
                services.append({"name": name, "source_node_id": row.get("id")})

    return services


def fetch_incidents(limit: int = 200) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for row in fetch_recent_nodes(limit=limit):
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
