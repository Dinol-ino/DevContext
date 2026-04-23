import json
import os
import re
from typing import Any

import requests

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

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "deepseek/deepseek-chat"


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


def _metadata_value(row: dict[str, Any], key: str) -> Any:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    return metadata.get(key)


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def call_llm(system_prompt: str, user_prompt: str) -> str:
    api_key = _clean_text(os.getenv("OPENROUTER_API_KEY"))
    model = _clean_text(os.getenv("OPENROUTER_MODEL")) or DEFAULT_MODEL
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
                "model": model,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        return _clean_text(data.get("choices", [{}])[0].get("message", {}).get("content", ""))
    except Exception:
        return ""


def format_sources(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        row_id = _clean_text(row.get("id")) or _clean_text(row.get("node_id")) or _clean_text(row.get("title"))
        if row_id in seen:
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
    query_terms = _tokenize(query)
    scored: list[tuple[float, dict[str, Any]]] = []

    for row in rows:
        label = _normalize_value(row.get("label") or row.get("title"))
        reason = _normalize_value(_metadata_value(row, "reason"))
        services = _normalize_value(_metadata_value(row, "services"))
        chunk = _normalize_value(row.get("chunk"))
        haystack = f"{label} {reason} {services} {chunk}"
        row_terms = _tokenize(haystack)
        overlap = query_terms.intersection(row_terms)
        if not overlap:
            continue

        score = float(len(overlap))
        if label and label.lower() in query.lower():
            score += 3.0
        if query.lower() in haystack.lower():
            score += 2.0
        enriched = dict(row)
        enriched["_score"] = round(score, 2)
        scored.append((score, enriched))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [row for _, row in scored[:limit]]


def search_nodes(question: str, limit: int = 5) -> list[dict[str, Any]]:
    return search_nodes_text(question, limit=limit)


def _graph_context(node_ids: list[str]) -> list[dict[str, Any]]:
    if not node_ids:
        return []
    related_edges = fetch_related_edges(node_ids)
    if not related_edges:
        return []

    recent_nodes = fetch_recent_nodes(limit=200)
    node_index = {_clean_text(row.get("id")): row for row in recent_nodes}
    neighbors: list[dict[str, Any]] = []
    for edge in related_edges:
        from_id = _clean_text(edge.get("from_node_id"))
        to_id = _clean_text(edge.get("to_node_id"))
        for node_id in (from_id, to_id):
            if node_id and node_id in node_index:
                neighbors.append(node_index[node_id])
    return neighbors


def retrieve_context(question: str) -> dict[str, Any]:
    lexical = search_nodes_text(question, limit=6)
    node_ids = [_clean_text(row.get("id")) for row in lexical if _clean_text(row.get("id"))]
    graph_rows = _graph_context(node_ids)
    recent = fetch_recent_nodes(limit=5)

    # No query embedding is generated yet; this falls back to any available chunks only if the table exists.
    embedding_rows = fetch_embedding_matches([], limit=5)

    combined = lexical + graph_rows + recent + embedding_rows
    ranked = _rank_rows(question, combined, limit=8)
    sources = format_sources(ranked)
    confidence = compute_confidence(question, ranked)
    return {"evidence": ranked, "sources": sources, "confidence": confidence}


def compute_confidence(question: str, evidence: list[dict[str, Any]]) -> float:
    if not evidence:
        return 0.0
    best_score = max(float(row.get("_score", 0.0)) for row in evidence)
    query_terms = _tokenize(question)
    coverage = min(1.0, len(evidence) / 4.0)
    score_component = min(1.0, best_score / max(1, len(query_terms) * 2))
    return round(min(0.95, 0.25 + (coverage * 0.3) + (score_component * 0.4)), 2)


def detect_conflict(diff_text: str) -> dict[str, Any]:
    text = _clean_text(diff_text)
    lowered = text.lower()
    decisions = fetch_decisions(limit=200)
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
    }

    for row in decisions:
        label = _clean_text(row.get("label"))
        if not label:
            continue
        label_terms = _tokenize(label)
        overlap = _tokenize(text).intersection(label_terms)
        if label.lower() in lowered or len(overlap) >= 2:
            matched_rules.append(label)

    for keyword in keyword_rules:
        if keyword in lowered and keyword not in matched_rules:
            matched_rules.append(keyword)

    if not matched_rules:
        return {
            "has_conflicts": False,
            "severity": "low",
            "matched_rules": [],
            "comment_text": "No conflicts detected against known architecture decisions.",
            "safe_to_merge": True,
        }

    severity = "low"
    for rule in matched_rules:
        rule_severity = keyword_rules.get(rule, "medium")
        if rule_severity == "high":
            severity = "high"
            break
        if rule_severity == "medium":
            severity = "medium"

    safe_to_merge = severity == "low" and len(matched_rules) <= 1
    return {
        "has_conflicts": True,
        "severity": severity,
        "matched_rules": matched_rules[:8],
        "comment_text": (
            f"Potential governance conflicts found for: {', '.join(matched_rules[:5])}. "
            "Review the diff against existing architectural decisions."
        ),
        "safe_to_merge": safe_to_merge,
    }


def analyze_incident(alert_title: str, service_name: str, error_snippet: str) -> dict[str, Any]:
    combined = " ".join([_clean_text(alert_title), _clean_text(service_name), _clean_text(error_snippet)]).lower()
    history = _rank_rows(combined, fetch_incidents(limit=100), limit=3)
    likely_cause = "Insufficient signal. Check recent changes, logs, and service health."
    severity = "low"
    issue_parts: list[str] = []
    fix_steps: list[str] = []
    warnings: list[str] = []

    if "pool" in combined or "connection" in combined or "db" in combined:
        issue_parts.append("database saturation")
        likely_cause = "Connection pool exhaustion or slow database queries."
        severity = "high"
        fix_steps.extend(
            [
                "Check database connection pool usage and active sessions.",
                "Inspect slow queries and recent schema or config changes.",
                "Reduce traffic or increase capacity if the pool is exhausted.",
            ]
        )
        warnings.append("Capture DB metrics before restarting services.")

    if "timeout" in combined or "latency" in combined:
        issue_parts.append("upstream timeout chain")
        if severity != "high":
            severity = "medium"
        likely_cause = "Slow upstream dependency or misconfigured timeouts."
        fix_steps.extend(
            [
                "Trace the request path in logs or APM.",
                "Check retry behavior and upstream latency.",
            ]
        )
        warnings.append("Retries can amplify the incident if upstream is failing.")

    if "gateway" in combined or "rate limit" in combined:
        issue_parts.append("gateway routing or throttling issue")
        if severity == "low":
            severity = "medium"
        likely_cause = "Gateway throttling, auth propagation, or routing regression."
        fix_steps.extend(
            [
                "Review gateway logs, route policies, and auth header forwarding.",
                "Validate rate-limit thresholds and upstream health checks.",
            ]
        )

    if "payment" in combined:
        issue_parts.append("payment flow degradation")
        severity = "high"
        likely_cause = "Payment provider instability or asynchronous backlog."
        fix_steps.extend(
            [
                "Check failed transactions, webhook backlog, and provider status.",
                "Confirm idempotency handling before retrying requests.",
            ]
        )
        warnings.append("Avoid replaying payment operations without idempotency.")

    if not issue_parts:
        issue = "General service incident requiring investigation."
        fix_steps = [
            "Collect request IDs, timestamps, and affected routes.",
            "Check recent deploys, config changes, and upstream dependencies.",
            "Escalate to the owning service team with evidence.",
        ]
    else:
        issue = f"Incident indicates {'; '.join(issue_parts)}."

    if history:
        likely_cause += f" Similar historical records found: {', '.join(_clean_text(row.get('label')) for row in history)}."

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
