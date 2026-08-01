from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
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
DEFAULT_MODEL = "deepseek/deepseek-chat"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIMENSIONS = 384
EMBEDDING_MAX_TEXT_LENGTH = 4000
RECENT_KEYWORDS = {"recent", "latest", "changed", "change", "updated", "new"}
DECISION_KEYWORDS = {"decision", "why", "architecture", "architectural", "rationale"}
SERVICE_KEYWORDS = {"gateway", "auth", "db", "api", "frontend"}


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


def get_used_model() -> str:
    return _current_model()


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


def _get_embedding_model():
    """Return a cached local SentenceTransformer instance."""
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
        return SentenceTransformer(EMBEDDING_MODEL)
    except Exception:
        return None


_EMBEDDING_MODEL_CACHE: list = []


def _get_cached_model():
    if not _EMBEDDING_MODEL_CACHE:
        m = _get_embedding_model()
        _EMBEDDING_MODEL_CACHE.append(m)
    return _EMBEDDING_MODEL_CACHE[0]


def _generate_query_embedding(text: str) -> list[float]:
    cleaned = _trim_text(text)
    if not cleaned:
        return []

    model = _get_cached_model()
    if model is None:
        return []

    try:
        vector = model.encode(cleaned, normalize_embeddings=True)
        return [float(v) for v in vector]
    except Exception:
        return []


def _source_key(row: dict[str, Any]) -> str:
    return (
        _clean_text(row.get("chunk_id"))
        or _clean_text(row.get("embedding_id"))
        or _clean_text(row.get("id"))
        or _clean_text(row.get("node_id"))
    )


def format_sources(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    seen: set[str] = set()

    for row in rows:
        row_id = _source_key(row)
        if not row_id or row_id in seen:
            continue
        seen.add(row_id)
        sources.append(
            {
                "id": row_id,
                "node_id": row.get("node_id") or row.get("id"),
                "chunk_id": row.get("chunk_id") or row.get("embedding_id"),
                "title": row.get("label") or row.get("title") or row.get("file_path"),
                "type": row.get("type"),
                "reason": _metadata_value(row, "reason"),
                "services": _metadata_value(row, "services"),
                "url": row.get("source_url"),
                "repo_id": row.get("repo_id"),
                "file_path": row.get("file_path"),
                "language": row.get("language"),
                "start_line": row.get("start_line"),
                "end_line": row.get("end_line"),
                "score": row.get("_score"),
                "similarity": row.get("_vector_score"),
            }
        )

    return sources


def _trim_context_chunk(value: Any, limit: int = 1800) -> str:
    text = _clean_text(value)
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n...[truncated]"


def _evidence_prompt(evidence: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for index, row in enumerate(evidence[:6], start=1):
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        reason = str(metadata.get("reason") or "").strip()
        services = metadata.get("services") if isinstance(metadata.get("services"), list) else []
        file_path = _clean_text(row.get("file_path"))
        line_span = ""
        if row.get("start_line") and row.get("end_line"):
            line_span = f":{row.get('start_line')}-{row.get('end_line')}"
        chunk = _trim_context_chunk(row.get("chunk"))
        header = (
            f"Evidence {index} | Title: {row.get('label') or row.get('title') or file_path or 'Unknown'} | "
            f"Type: {row.get('type') or 'n/a'} | "
            f"Repo: {row.get('repo_id') or 'n/a'} | "
            f"File: {(file_path + line_span) if file_path else 'n/a'} | "
            f"Similarity: {row.get('_vector_score', 'n/a')} | Score: {row.get('_score', 'n/a')}"
        )
        details = (
            f"Reason: {reason or 'n/a'}\n"
            f"Services: {', '.join(str(item) for item in services) if services else 'n/a'}"
        )
        if chunk:
            details += f"\nCode Context:\n```\n{chunk}\n```"
        blocks.append(f"{header}\n{details}")
    return "\n\n".join(blocks)


def _rank_rows(query: str, rows: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    return _rank_rows_with_intent(query, rows, intent=None, limit=limit)


def _parse_created_at(value: Any) -> datetime | None:
    text = _clean_text(value)
    if not text:
        return None
    candidate = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _freshness_weight(row: dict[str, Any]) -> float:
    created_at = _parse_created_at(row.get("created_at"))
    if created_at is None:
        return 0.1

    now = datetime.now(timezone.utc)
    age_days = max(0.0, (now - created_at).total_seconds() / 86400.0)
    if age_days <= 7:
        return 1.0
    if age_days <= 30:
        return 0.8
    if age_days <= 90:
        return 0.6
    if age_days <= 180:
        return 0.35
    return 0.15


def _infer_query_intent(question: str) -> dict[str, Any]:
    lowered = _clean_text(question).lower()
    has_recent_intent = any(keyword in lowered for keyword in RECENT_KEYWORDS)
    has_decision_intent = any(keyword in lowered for keyword in DECISION_KEYWORDS)
    matched_services = [service for service in SERVICE_KEYWORDS if service in lowered]
    return {
        "recent": has_recent_intent,
        "decision": has_decision_intent,
        "services": matched_services,
    }


def _row_text_blobs(row: dict[str, Any]) -> list[str]:
    label = _normalize_value(row.get("label") or row.get("title"))
    reason = _normalize_value(_metadata_value(row, "reason"))
    services = _normalize_value(_metadata_value(row, "services"))
    chunk = _normalize_value(row.get("chunk"))
    return [label, reason, services, chunk]


def _row_has_exact_match(question: str, row: dict[str, Any]) -> bool:
    query = _clean_text(question).lower()
    if not query:
        return False
    for blob in _row_text_blobs(row):
        lowered = blob.lower()
        if lowered and (query in lowered or lowered in query):
            return True
    return False


def _service_lexical_search(question: str, services: list[str], limit: int = 8, repo_id: str | None = None) -> list[dict[str, Any]]:
    if not services:
        return []

    rows = fetch_recent_nodes(limit=350, repo_id=repo_id)
    query = _clean_text(question).lower()
    scored: list[tuple[float, dict[str, Any]]] = []

    for row in rows:
        label = _normalize_value(row.get("label")).lower()
        metadata_blob = _normalize_value(row.get("metadata")).lower()
        score = 0.0

        for service in services:
            if service in label:
                score += 3.0
            if service in metadata_blob:
                score += 2.0

        if query and query in label:
            score += 2.0

        if score <= 0:
            continue

        enriched = dict(row)
        enriched["_score"] = max(float(enriched.get("_score", 0.0)), round(score, 4))
        scored.append((score, enriched))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [row for _, row in scored[: max(1, limit)]]


def _rank_rows_with_intent(
    query: str,
    rows: list[dict[str, Any]],
    intent: dict[str, Any] | None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    query_text = _clean_text(query)
    query_terms = _tokenize(query_text)
    lowered_query = query_text.lower()
    intent_data = intent or {"recent": False, "decision": False, "services": []}
    service_terms = intent_data.get("services") if isinstance(intent_data.get("services"), list) else []
    scored: list[tuple[float, dict[str, Any]]] = []
    seen: set[str] = set()

    for row in rows:
        row_id = _source_key(row)
        key = row_id or f"{_clean_text(row.get('label'))}:{_clean_text(row.get('chunk'))}"
        if key in seen:
            continue
        seen.add(key)

        label = _normalize_value(row.get("label") or row.get("title"))
        node_type = _normalize_value(row.get("type"))
        reason = _normalize_value(_metadata_value(row, "reason"))
        services_val = _normalize_value(_metadata_value(row, "services"))
        chunk = _normalize_value(row.get("chunk"))
        haystack = " ".join(part for part in [label, node_type, reason, services_val, chunk] if part)
        haystack_lower = haystack.lower()
        row_terms = _tokenize(haystack)
        overlap = query_terms.intersection(row_terms)

        lexical_score = float(len(overlap))
        if label and label.lower() in lowered_query:
            lexical_score += 4.0
        if lowered_query in haystack_lower and lowered_query:
            lexical_score += 2.5
        if services_val:
            lexical_score += min(2.0, len(query_terms.intersection(_tokenize(services_val))) * 0.75)

        vector_score = float(row.get("_vector_score", 0.0)) * 4.0
        exact_match_bonus = 2.0 if _row_has_exact_match(query_text, row) else 0.0
        freshness = _freshness_weight(row)
        freshness_bonus = freshness * (1.8 if intent_data.get("recent") else 0.9)
        decision_bonus = 0.0
        if intent_data.get("decision") and node_type.lower() == "decision":
            decision_bonus = 2.5

        service_bonus = 0.0
        if service_terms:
            label_blob = label.lower()
            reason_blob = reason.lower()
            metadata_blob = _normalize_value(row.get("metadata")).lower()
            for term in service_terms:
                if term in label_blob:
                    service_bonus += 1.2
                if term in reason_blob or term in metadata_blob:
                    service_bonus += 1.0

        total_score = lexical_score + vector_score + exact_match_bonus + freshness_bonus + decision_bonus + service_bonus
        if total_score <= 0:
            continue

        enriched = dict(row)
        enriched["_score"] = round(total_score, 4)
        enriched["_freshness"] = round(freshness, 4)
        scored.append((total_score, enriched))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [row for _, row in scored[:limit]]


def search_nodes(question: str, limit: int = 5, repo_id: str | None = None) -> list[dict[str, Any]]:
    return search_nodes_text(question, limit=max(1, limit), repo_id=repo_id)


def _graph_context(node_ids: list[str], repo_id: str | None = None) -> list[dict[str, Any]]:
    clean_ids = list(dict.fromkeys(_clean_text(node_id) for node_id in node_ids if _clean_text(node_id)))
    if not clean_ids:
        return []

    related_edges = fetch_related_edges(clean_ids)
    if not related_edges:
        return []

    recent_nodes = fetch_recent_nodes(limit=300, repo_id=repo_id)
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


def retrieve_context(question: str, repo_id: str | None = None) -> dict[str, Any]:
    intent = _infer_query_intent(question)
    lexical_rows = search_nodes(question, limit=8, repo_id=repo_id)
    query_embedding = _generate_query_embedding(question)
    vector_rows = fetch_embedding_matches(query_embedding, limit=6, repo_id=repo_id) if query_embedding else []
    recent_rows = fetch_recent_nodes(limit=10 if intent.get("recent") else 4, repo_id=repo_id)
    decision_rows = fetch_decisions(limit=120, repo_id=repo_id) if intent.get("decision") else []
    decision_focus_rows = _rank_rows_with_intent(question, decision_rows, intent=intent, limit=8) if decision_rows else []
    service_rows = _service_lexical_search(question, intent.get("services", []), limit=8, repo_id=repo_id)

    node_ids = [
        _clean_text(row.get("node_id") or row.get("id"))
        for row in lexical_rows + vector_rows + decision_focus_rows + service_rows
        if _clean_text(row.get("id") or row.get("node_id"))
    ]

    graph_rows = _graph_context(node_ids, repo_id=repo_id)

    combined = lexical_rows + vector_rows + decision_focus_rows + service_rows + graph_rows + recent_rows
    ranked = _rank_rows_with_intent(question, combined, intent=intent, limit=8)
    sources = format_sources(ranked)
    confidence = compute_confidence(question, ranked, intent=intent)
    return {"evidence": ranked, "sources": sources, "confidence": confidence}


def compute_confidence(
    question: str,
    evidence: list[dict[str, Any]],
    intent: dict[str, Any] | None = None,
) -> float:
    if not evidence:
        return 0.0

    intent_data = intent or _infer_query_intent(question)
    considered = evidence[:8]

    evidence_count_score = min(0.34, len(considered) * 0.05)
    freshness_values = [_freshness_weight(row) for row in considered]
    freshness_score = min(0.2, (sum(freshness_values) / max(1, len(freshness_values))) * 0.2)
    exact_matches = sum(1 for row in considered if _row_has_exact_match(question, row))
    exact_match_score = min(0.24, exact_matches * 0.08)
    decision_hits = sum(1 for row in considered if _clean_text(row.get("type")).lower() == "decision")
    decision_multiplier = 0.06 if intent_data.get("decision") else 0.03
    decision_score = min(0.18 if intent_data.get("decision") else 0.1, decision_hits * decision_multiplier)

    base = 0.1
    return round(min(0.96, base + evidence_count_score + freshness_score + exact_match_score + decision_score), 2)


def detect_conflict(diff_text: str) -> dict[str, Any]:
    text = _clean_text(diff_text)
    if not text:
        return {
            "has_conflicts": False,
            "severity": "low",
            "matched_rules": [],
            "comment_text": "Empty diff provided. No conflicts detected.",
            "safe_to_merge": True,
        }

    query_terms = _tokenize(text)
    lowered = text.lower()
    decisions = fetch_decisions(limit=300)

    matched_conflicts: list[dict[str, Any]] = []
    matched_labels: list[str] = []

    for row in decisions:
        label = _clean_text(row.get("label"))
        if not label:
            continue

        label_lower = label.lower()
        overlap = query_terms.intersection(_tokenize(label))
        metadata = _metadata_value(row, "reason") or ""

        # Match if decision label or reason shares significant context with diff
        if label_lower in lowered or len(overlap) >= 2 or (metadata and any(term in lowered for term in _tokenize(str(metadata)) if len(term) > 4)):
            risk = str(_metadata_value(row, "risk") or "medium").lower()
            reason = str(_metadata_value(row, "reason") or f"Matched architecture decision: {label}").strip()
            matched_conflicts.append({
                "label": label,
                "reason": reason,
                "risk": risk if risk in {"high", "medium", "low"} else "medium",
                "url": row.get("source_url"),
            })
            matched_labels.append(label)

    # Check for critical security and architectural code smells in the diff text
    danger_patterns = [
        ("bypass", "Potential security/auth bypass detected in code changes"),
        ("disable_auth", "Disabling authentication guard controls"),
        ("unauthenticated", "Allowing unauthenticated access to protected boundaries"),
        ("hardcoded", "Hardcoded credentials or sensitive configuration detected"),
        ("disable_rate_limit", "Disabling API rate limiting or throttling controls"),
        ("skip_validation", "Skipping input/security validation checks"),
    ]

    for pattern, description in danger_patterns:
        if pattern in lowered:
            matched_conflicts.append({
                "label": f"AI Risk Guard: {pattern.replace('_', ' ').title()}",
                "reason": description,
                "risk": "high" if any(p in pattern for p in ["bypass", "unauthenticated", "disable_auth"]) else "medium",
                "url": "adr://ai-risk-guard",
            })
            matched_labels.append(f"AI Guard: {pattern.replace('_', ' ').title()}")

    if not matched_conflicts:
        return {
            "has_conflicts": False,
            "severity": "low",
            "matched_rules": [],
            "comment_text": "No conflicts detected against stored architecture decisions or security rules.",
            "safe_to_merge": True,
        }

    has_high = any(c["risk"] == "high" for c in matched_conflicts)
    has_medium = any(c["risk"] == "medium" for c in matched_conflicts)
    severity = "high" if has_high else ("medium" if has_medium or len(matched_conflicts) > 1 else "low")

    explanations = [f"• {c['label']}: {c['reason']}" for c in matched_conflicts[:5]]
    comment_text = (
        f"Detected {len(matched_conflicts)} potential architecture/security conflict(s):\n"
        + "\n".join(explanations)
    )

    return {
        "has_conflicts": True,
        "severity": severity,
        "matched_rules": matched_labels[:8],
        "conflicts": matched_conflicts,
        "comment_text": comment_text,
        "safe_to_merge": severity == "low",
    }


def analyze_incident(alert_title: str, service_name: str, error_snippet: str) -> dict[str, Any]:
    alert = _clean_text(alert_title)
    service = _clean_text(service_name)
    snippet = _clean_text(error_snippet)
    combined_query = f"{alert} {service} {snippet}".strip()

    # Dynamic RAG over stored incident, service, and decision nodes
    rag_result = retrieve_context(combined_query)
    evidence = rag_result.get("evidence", [])

    history_incidents = fetch_incidents(limit=100)
    matched_history = _rank_rows(combined_query, history_incidents, limit=3)

    system_prompt = (
        "You are an expert SRE and Incident Response Agent. Analyze the incident alert, service, error snippet, "
        "and retrieved architectural/incident context. Output ONLY JSON with keys: "
        '{"issue": string, "severity": "high"|"medium"|"low", "likely_cause": string, '
        '"fix_steps": list[string], "warnings": list[string]}'
    )
    user_prompt = (
        f"Alert: {alert}\nService: {service}\nSnippet: {snippet}\n\n"
        f"Retrieved Architecture Evidence:\n{_evidence_prompt(evidence[:4])}\n"
        f"Historical Incidents Count: {len(matched_history)}"
    )

    llm_raw = call_llm(system_prompt, user_prompt)
    parsed = parse_json_response(llm_raw)

    if parsed and isinstance(parsed.get("fix_steps"), list) and parsed.get("issue"):
        return {
            "issue": _clean_text(parsed.get("issue")),
            "severity": _clean_text(parsed.get("severity")) or "medium",
            "likely_cause": _clean_text(parsed.get("likely_cause")),
            "fix_steps": [_clean_text(step) for step in parsed.get("fix_steps") if _clean_text(step)],
            "warnings": [_clean_text(w) for w in parsed.get("warnings", []) if _clean_text(w)],
        }

    # Dynamic fallback synthesis directly from RAG evidence
    issue_desc = f"Operational incident affecting service '{service or 'unknown'}'"
    if alert:
        issue_desc += f": {alert}"

    likely_cause_desc = "Signal requires investigation."
    if evidence:
        causes = [str(_metadata_value(row, "reason") or row.get("label")) for row in evidence[:2] if row.get("label")]
        if causes:
            likely_cause_desc = f"Potential context correlation with stored decisions: {'; '.join(causes)}."

    if matched_history:
        history_labels = ", ".join(_clean_text(row.get("label")) for row in matched_history if row.get("label"))
        if history_labels:
            likely_cause_desc += f" Similar historical incident records: {history_labels}."

    steps = [
        f"Inspect active logs, metrics, and tracing for service '{service or 'affected service'}'.",
        "Verify recent deployment changes, config updates, and upstream status.",
        "Check database connection pool, latency counters, and rate limit errors.",
    ]

    warnings_list = [
        "Capture memory dumps and log snapshots prior to restarting instances.",
    ]

    return {
        "issue": issue_desc,
        "severity": "medium" if (evidence or matched_history) else "low",
        "likely_cause": likely_cause_desc,
        "fix_steps": steps,
        "warnings": warnings_list,
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
