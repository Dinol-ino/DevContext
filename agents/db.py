import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from supabase import Client, create_client

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=ENV_FILE)


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    if isinstance(value, dict):
        return " ".join(str(item) for item in value.values())
    return str(value)


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


@lru_cache(maxsize=1)
def get_client() -> Optional[Client]:
    url = _clean_text(os.getenv("SUPABASE_URL"))
    key = _clean_text(os.getenv("SUPABASE_SERVICE_ROLE_KEY"))
    if not url or not key:
        return None
    try:
        return create_client(url, key)
    except Exception:
        return None


def get_supabase_client() -> Optional[Client]:
    return get_client()


def health_check() -> bool:
    client = get_client()
    if client is None:
        return False
    try:
        client.table("nodes").select("label").limit(1).execute()
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
    capped_limit = max(1, min(limit, 200))

    try:
        response = (
            client.table("nodes")
            .select("*")
            .order("created_at", desc=True)
            .limit(capped_limit)
            .execute()
        )
        return response.data or []
    except Exception:
        return _safe_select("nodes", limit=capped_limit)


def fetch_nodes(limit: int = 200) -> list[dict[str, Any]]:
    return _safe_select("nodes", limit=limit)


def search_nodes_text(query: str, limit: int = 10) -> list[dict[str, Any]]:
    query_text = _clean_text(query)
    if not query_text:
        return []

    query_terms = _tokenize(query_text)
    rows = fetch_recent_nodes(limit=200)
    scored: list[tuple[float, dict[str, Any]]] = []

    for row in rows:
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        label = _normalize_value(row.get("label"))
        reason = _normalize_value(metadata.get("reason"))
        services = _normalize_value(metadata.get("services"))
        source_url = _normalize_value(row.get("source_url"))
        haystack = f"{label} {reason} {services} {source_url}"
        field_terms = _tokenize(haystack)
        overlap = query_terms.intersection(field_terms)
        if not overlap:
            continue

        score = float(len(overlap))
        if label and label.lower() in query_text.lower():
            score += 4.0
        if query_text.lower() in haystack.lower():
            score += 2.0

        enriched = dict(row)
        enriched["_score"] = round(score, 2)
        scored.append((score, enriched))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [row for _, row in scored[: max(1, limit)]]


def fetch_related_edges(node_ids: list[str]) -> list[dict[str, Any]]:
    client = get_client()
    if client is None or not node_ids:
        return []

    collected: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    try:
        for field_name in ("from_node_id", "to_node_id"):
            response = (
                client.table("edges")
                .select("*")
                .in_(field_name, node_ids)
                .limit(200)
                .execute()
            )
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


def fetch_embedding_matches(query_embedding: list[float], limit: int = 5) -> list[dict[str, Any]]:
    if not query_embedding:
        return []
    client = get_client()
    if client is None:
        return []

    try:
        response = client.table("node_embeddings").select("node_id,chunk").limit(max(1, min(limit, 20))).execute()
    except Exception:
        return []
    return response.data or []


def fetch_decisions(limit: int = 200) -> list[dict[str, Any]]:
    return [row for row in fetch_recent_nodes(limit=limit) if _clean_text(row.get("type")).lower() == "decision"]


def fetch_services(limit: int = 200) -> list[dict[str, Any]]:
    services: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in fetch_decisions(limit=limit):
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        raw_services = metadata.get("services")
        if isinstance(raw_services, list):
            for service in raw_services:
                name = _clean_text(service)
                if name and name not in seen:
                    seen.add(name)
                    services.append({"name": name, "source_node_id": row.get("id")})
    return services


def fetch_incidents(limit: int = 200) -> list[dict[str, Any]]:
    incident_like: list[dict[str, Any]] = []
    for row in fetch_recent_nodes(limit=limit):
        row_type = _clean_text(row.get("type")).lower()
        label = _clean_text(row.get("label")).lower()
        if row_type == "incident" or "incident" in label or "alert" in label or "outage" in label:
            incident_like.append(row)
    return incident_like
