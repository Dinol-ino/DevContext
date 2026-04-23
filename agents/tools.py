from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

try:
    from .db import (
        fetch_decisions,
        fetch_embedding_matches,
        fetch_incidents,
        fetch_recent_nodes,
        fetch_related_edges,
        search_nodes_text,
    )
except ImportError:
    from db import (
        fetch_decisions,
        fetch_embedding_matches,
        fetch_incidents,
        fetch_recent_nodes,
        fetch_related_edges,
        search_nodes_text,
    )

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=ENV_FILE, override=False)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENAI_EMBEDDINGS_URL = "https://api.openai.com/v1/embeddings"
DEFAULT_MODEL = "deepseek/deepseek-chat"
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 768
EMBEDDING_MAX_TEXT_LENGTH = 4000


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


def _metadata_value(row: dict[str, Any], key: str) -> Any:
    metadata = row.get("metadata")
    if isinstance(metadata, dict):
        return metadata.get(key)
    return None


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", _clean_text(text).lower()))


def _trim_text(text: str, limit: int = EMBEDDING_MAX_TEXT_LENGTH) -> str:
    cleaned = _clean_text(text)
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].strip()


def _current_model() -> str:
    return _clean_text(os.getenv("MODEL_NAME")) or _clean_text(os.getenv("OPENROUTER_MODEL")) or DEFAULT_MODEL


def call_llm(system_prompt: str, user_prompt: str) -> str:
    api_key = _clean_text(os.getenv("OPENROUTER_API_KEY"))
    if not api_key:
        return ""

    try:
        response = requests.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": _current_model(),
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": _clean_text(system_prompt)},
                    {"role": "user", "content": _clean_text(user_prompt)},
                ],
            },
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        return _clean_text(data.get("choices", [{}])[0].get("message", {}).get("content", ""))
    except Exception:
        return ""


def _generate_query_embedding(text: str) -> list[float]:
    cleaned = _trim_text(text)
    if not cleaned:
        return []

    api_key = _clean_text(os.getenv("OPENAI_API_KEY"))
    if not api_key:
        return []

    payload = {
        "model": EMBEDDING_MODEL,
        "input": cleaned,
        "dimensions": EMBEDDING_DIMENSIONS,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    for attempt in range(2):
        try:
            response = requests.post(
                OPENAI_EMBEDDINGS_URL,
                headers=headers,
                json=payload,
                timeout=20,
            )
            response.raise_for_status()
            data = response.json()
            embedding = data.get("data", [{}])[0].get("embedding", [])
            if not isinstance(embedding, list) or not embedding:
                return []
            return [float(value) for value in embedding]
        except Exception:
            if attempt == 1:
                return []
            time.sleep(1)

    return []


def format_sources(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    seen: set[str] = set()

    for row in rows:
        row_id = _clean_text(row.get("id")) or _clean_text(row.get("node_id"))
        if not row_id or row_id in seen:
            continue
        seen.add(row_id)
        sources.append(
            {
                "id": row.get("id") or row.get("node_id"),
                "title": row.get("label") or row.get("title"),
                "type": row.get("type"),
                "reason": _metadata_value(row, "reason"),
                "services": _metadata_value(row, "services"),
                "url": row.get("source_url"),
            }
        )

    return sources


def _rank_rows(query: str, rows: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    query_text = _clean_text(query)
    query_terms = _tokenize(query_text)
    scored: list[tuple[float, dict[str, Any]]] = []
    seen: set[str] = set()

    for row in rows:
        row_id = _clean_text(row.get("id")) or _clean_text(row.get("node_id"))
        key = row_id or f"{_clean_text(row.get('label'))}:{_clean_text(row.get('chunk'))}"
        if key in seen:
            continue
        seen.add(key)

        label = _normalize_value(row.get("label") or row.get("title"))
        node_type = _normalize_value(row.get("type"))
        reason = _normalize_value(_metadata_value(row, "reason"))
        services = _normalize_value(_metadata_value(row, "services"))
        chunk = _normalize_value(row.get("chunk"))
        haystack = " ".join(part for part in [label, node_type, reason, services, chunk] if part)
        haystack_lower = haystack.lower()
        row_terms = _tokenize(haystack)
        overlap = query_terms.intersection(row_terms)

        lexical_score = float(len(overlap))
        if label and label.lower() in query_text.lower():
            lexical_score += 4.0
        if query_text.lower() in haystack_lower and query_text:
            lexical_score += 2.5
        if services:
            lexical_score += min(2.0, len(query_terms.intersection(_tokenize(services))) * 0.75)

        vector_score = float(row.get("_vector_score", 0.0)) * 4.0
        total_score = lexical_score + vector_score
        if total_score <= 0:
            continue

        enriched = dict(row)
        enriched["_score"] = round(total_score, 4)
        scored.append((total_score, enriched))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [row for _, row in scored[:limit]]


def search_nodes(question: str, limit: int = 5) -> list[dict[str, Any]]:
    return search_nodes_text(question, limit=max(1, limit))


def _graph_context(node_ids: list[str]) -> list[dict[str, Any]]:
    clean_ids = [_clean_text(node_id) for node_id in node_ids if _clean_text(node_id)]
    if not clean_ids:
        return []

    related_edges = fetch_related_edges(clean_ids)
    if not related_edges:
        return []

    recent_nodes = fetch_recent_nodes(limit=300)
    node_index = {_clean_text(row.get("id")): row for row in recent_nodes if _clean_text(row.get("id"))}

    neighbors: list[dict[str, Any]] = []
    seen: set[str] = set()
    for edge in related_edges:
        for node_id in (_clean_text(edge.get("from_node_id")), _clean_text(edge.get("to_node_id"))):
            if not node_id or node_id not in node_index or node_id in seen:
                continue
            seen.add(node_id)
            node = dict(node_index[node_id])
            node["_score"] = max(float(node.get("_score", 0.0)), 1.0)
            neighbors.append(node)

    return neighbors


def retrieve_context(question: str) -> dict[str, Any]:
    lexical_rows = search_nodes(question, limit=6)
    query_embedding = _generate_query_embedding(question)
    vector_rows = fetch_embedding_matches(query_embedding, limit=6) if query_embedding else []

    node_ids = [
        _clean_text(row.get("id") or row.get("node_id"))
        for row in lexical_rows + vector_rows
        if _clean_text(row.get("id") or row.get("node_id"))
    ]

    graph_rows = _graph_context(node_ids)
    recent_rows = fetch_recent_nodes(limit=5)

    combined = lexical_rows + vector_rows + graph_rows + recent_rows
    ranked = _rank_rows(question, combined, limit=8)
    sources = format_sources(ranked)
    confidence = compute_confidence(question, ranked)
    return {"evidence": ranked, "sources": sources, "confidence": confidence}


def compute_confidence(question: str, evidence: list[dict[str, Any]]) -> float:
    if not evidence:
        return 0.0

    query_terms = _tokenize(question)
    best_score = max(float(row.get("_score", 0.0)) for row in evidence)
    vector_hits = sum(1 for row in evidence if float(row.get("_vector_score", 0.0)) > 0)
    base = min(0.45, len(evidence) * 0.08)
    lexical = min(0.35, best_score / max(4.0, len(query_terms) * 1.5))
    vector = min(0.15, vector_hits * 0.05)
    return round(min(0.95, 0.15 + base + lexical + vector), 2)


def detect_conflict(diff_text: str) -> dict[str, Any]:
    text = _clean_text(diff_text)
    lowered = text.lower()
    query_terms = _tokenize(text)
    matched_rules: list[str] = []

    keyword_rules = {
        "bypass auth": "high",
        "remove rate limiting": "high",
        "direct db access": "high",
        "secret": "high",
        "token": "high",
        "rate limit": "medium",
        "gateway": "medium",
        "auth": "high",
        "db": "high",
        "retry": "medium",
        "payment": "high",
        "cache": "medium",
    }

    for row in fetch_decisions(limit=200):
        label = _clean_text(row.get("label"))
        if not label:
            continue

        label_lower = label.lower()
        overlap = query_terms.intersection(_tokenize(label))
        if label_lower in lowered or len(overlap) >= 2:
            matched_rules.append(label)

    for keyword in keyword_rules:
        if keyword in lowered and keyword not in matched_rules:
            matched_rules.append(keyword)

    if not matched_rules:
        return {
            "has_conflicts": False,
            "severity": "low",
            "matched_rules": [],
            "comment_text": "No conflicts detected against stored architecture decisions.",
            "safe_to_merge": True,
        }

    severity = "low"
    if any(keyword_rules.get(rule) == "high" for rule in matched_rules):
        severity = "high"
    elif any(keyword_rules.get(rule) == "medium" for rule in matched_rules) or len(matched_rules) > 1:
        severity = "medium"

    return {
        "has_conflicts": True,
        "severity": severity,
        "matched_rules": matched_rules[:8],
        "comment_text": (
            f"Potential governance conflicts found for: {', '.join(matched_rules[:5])}. "
            "Review this diff against stored decisions before merging."
        ),
        "safe_to_merge": severity == "low",
    }


def analyze_incident(alert_title: str, service_name: str, error_snippet: str) -> dict[str, Any]:
    alert = _clean_text(alert_title)
    service = _clean_text(service_name)
    snippet = _clean_text(error_snippet)
    combined = " ".join(part for part in [alert, service, snippet] if part).lower()

    history_rows = _rank_rows(combined, fetch_incidents(limit=150), limit=3)
    issue = "General service incident requiring investigation."
    severity = "low"
    likely_cause = "Signal is limited. Check recent deploys, config changes, and service health."
    fix_steps: list[str] = []
    warnings: list[str] = []

    if any(keyword in combined for keyword in ["db", "database", "pool", "connection"]):
        issue = "Database saturation or connection exhaustion."
        severity = "high"
        likely_cause = "Connection pool exhaustion, blocked queries, or database resource pressure."
        fix_steps.extend(
            [
                "Check active DB sessions, pool usage, and slow query logs.",
                "Review recent deploys or migrations that changed query behavior.",
                "Reduce traffic or scale capacity if the database is saturated.",
            ]
        )
        warnings.append("Avoid restarting blindly before capturing DB evidence.")

    if "timeout" in combined or "latency" in combined:
        if severity != "high":
            severity = "medium"
        likely_cause = "Upstream latency, retry amplification, or timeout misconfiguration."
        fix_steps.extend(
            [
                "Trace request latency across upstream dependencies.",
                "Check timeout and retry settings on the affected path.",
            ]
        )
        warnings.append("Retries can worsen a partial outage if the dependency is degraded.")

    if "gateway" in combined or "rate limit" in combined:
        if severity == "low":
            severity = "medium"
        issue = "Gateway routing, throttling, or policy degradation."
        likely_cause = "Gateway policy changes, upstream backpressure, or auth propagation issues."
        fix_steps.extend(
            [
                "Inspect gateway logs, route policies, and throttling counters.",
                "Validate auth headers, upstream health checks, and recent config changes.",
            ]
        )

    if "payment" in combined:
        issue = "Payment flow degradation."
        severity = "high"
        likely_cause = "Provider instability, webhook backlog, or non-idempotent retry behavior."
        fix_steps.extend(
            [
                "Check provider status, failed transactions, and webhook processing backlog.",
                "Verify idempotency protections before replaying payment operations.",
            ]
        )
        warnings.append("Do not replay payment requests without idempotency keys.")

    if not fix_steps:
        fix_steps = [
            "Collect timestamps, request IDs, and affected endpoints.",
            "Check recent deploys, config changes, and dependency health.",
            "Escalate to the owning service team with logs and metrics.",
        ]

    if history_rows:
        history_labels = ", ".join(_clean_text(row.get("label")) for row in history_rows if _clean_text(row.get("label")))
        if history_labels:
            likely_cause += f" Similar historical records: {history_labels}."

    deduped_steps: list[str] = []
    for step in fix_steps:
        if step not in deduped_steps:
            deduped_steps.append(step)

    deduped_warnings: list[str] = []
    for warning in warnings:
        if warning not in deduped_warnings:
            deduped_warnings.append(warning)

    return {
        "issue": issue,
        "severity": severity,
        "likely_cause": likely_cause,
        "fix_steps": deduped_steps,
        "warnings": deduped_warnings,
    }


def parse_json_response(text: str) -> dict[str, Any]:
    cleaned = _clean_text(text).replace("```json", "").replace("```", "").strip()
    if not cleaned:
        return {}
    try:
        value = json.loads(cleaned)
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}
