import re
from typing import Any

try:
    from .db import fetch_nodes
except ImportError:
    from db import fetch_nodes


def _normalize_token(token: str) -> str:
    token = token.lower().strip()
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("ing") and len(token) > 5:
        token = token[:-3]
    if token.endswith("ed") and len(token) > 4:
        token = token[:-2]
    if token.endswith("s") and len(token) > 3:
        token = token[:-1]
    return token


def _tokenize(text: str) -> set[str]:
    return {_normalize_token(token) for token in re.findall(r"[a-z0-9]+", text.lower())}


def _metadata_value(row: dict[str, Any], key: str) -> Any:
    metadata = row.get("metadata") or {}
    if isinstance(metadata, dict):
        return metadata.get(key)
    return None


def _normalize_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    if isinstance(value, dict):
        return " ".join(str(item) for item in value.values())
    return str(value)


def _decision_rows(limit: int = 200) -> list[dict[str, Any]]:
    rows = fetch_nodes(limit=limit)
    return [row for row in rows if (row.get("type") or "").lower() == "decision"]


def search_nodes(question: str, limit: int = 5) -> list[dict[str, Any]]:
    query_text = _normalize_value(question).strip()
    if not query_text:
        return []

    query_terms = _tokenize(query_text)
    if not query_terms:
        return []

    scored: list[tuple[float, dict[str, Any]]] = []
    for row in _decision_rows():
        label = _normalize_value(row.get("label"))
        reason = _normalize_value(_metadata_value(row, "reason"))
        services = _normalize_value(_metadata_value(row, "services"))

        field_map = {
            "label": (label, 4.0),
            "reason": (reason, 2.5),
            "services": (services, 2.0),
        }

        score = 0.0
        for field_name, (field_value, weight) in field_map.items():
            field_terms = _tokenize(field_value)
            if not field_terms:
                continue
            matches = query_terms.intersection(field_terms)
            if matches:
                score += len(matches) * weight
                if field_name == "label" and len(matches) == len(query_terms):
                    score += 2.0

        haystack = f"{label} {reason} {services}".lower()
        if query_text.lower() in haystack:
            score += 3.0

        if score > 0:
            enriched = dict(row)
            enriched["_match_score"] = round(score, 2)
            scored.append((score, enriched))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [row for _, row in scored[: max(1, limit)]]


def format_sources(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for row in rows:
        sources.append(
            {
                "id": row.get("id"),
                "title": row.get("label"),
                "type": row.get("type"),
                "reason": _metadata_value(row, "reason"),
                "services": _metadata_value(row, "services"),
                "url": row.get("source_url"),
            }
        )
    return sources


def detect_conflict(diff_text: str) -> dict[str, Any]:
    text = _normalize_value(diff_text)
    lowered = text.lower()

    keyword_rules = {
        "rate limit": "medium",
        "gateway": "medium",
        "auth": "high",
        "db": "high",
        "retry": "medium",
        "payment": "high",
        "token": "high",
        "cache": "low",
    }

    matched_rules: list[str] = []

    for row in _decision_rows():
        label = _normalize_value(row.get("label"))
        label_terms = _tokenize(label)
        diff_terms = _tokenize(text)
        overlap = diff_terms.intersection(label_terms)
        if label and (label.lower() in lowered or len(overlap) >= 2):
            matched_rules.append(label)

    for keyword in keyword_rules:
        if keyword in lowered and keyword not in matched_rules:
            matched_rules.append(keyword)

    if not matched_rules:
        return {
            "has_conflicts": False,
            "severity": "low",
            "matched_rules": [],
            "comment_text": "No conflicts detected against known decisions or governance keywords.",
            "safe_to_merge": True,
        }

    severity = "low"
    for rule in matched_rules:
        level = keyword_rules.get(rule, "medium")
        if level == "high":
            severity = "high"
            break
        if level == "medium":
            severity = "medium"

    safe_to_merge = severity == "low" and len(matched_rules) <= 1
    comment_text = (
        f"Potential governance conflict detected for: {', '.join(matched_rules[:5])}. "
        "Check implementation alignment with existing decisions before merging."
    )

    return {
        "has_conflicts": True,
        "severity": severity,
        "matched_rules": matched_rules[:8],
        "comment_text": comment_text,
        "safe_to_merge": safe_to_merge,
    }


def analyze_incident(alert_title: str, service_name: str, error_snippet: str) -> dict[str, Any]:
    alert_text = _normalize_value(alert_title)
    service_text = _normalize_value(service_name)
    error_text = _normalize_value(error_snippet)
    combined = f"{alert_text} {service_text} {error_text}".lower()

    issue_parts: list[str] = []
    fix_steps: list[str] = []
    warnings: list[str] = []
    likely_cause = "Insufficient signal. Review logs, recent deploys, and service dashboards."
    severity = "low"

    if "db" in combined or "connection" in combined or "pool" in combined:
        issue_parts.append("database connectivity pressure")
        likely_cause = "Database connection exhaustion, slow queries, or pool saturation."
        severity = "high"
        fix_steps.extend(
            [
                "Check connection pool usage and active sessions.",
                "Inspect slow queries and recent migrations affecting the service.",
                "Reduce traffic or increase pool capacity if the service is saturated.",
            ]
        )
        warnings.append("Avoid restarting services before capturing DB metrics.")

    if "timeout" in combined or "latency" in combined:
        issue_parts.append("request timeout chain")
        if severity != "high":
            severity = "medium"
        likely_cause = "Upstream dependency latency or aggressive timeout settings."
        fix_steps.extend(
            [
                "Trace the slow path in logs or APM spans.",
                "Check upstream dependency latency and retry behavior.",
            ]
        )
        warnings.append("Retries can amplify traffic during an incident.")

    if "payment" in combined:
        issue_parts.append("payment flow degradation")
        severity = "high"
        likely_cause = "Payment provider failure, webhook backlog, or duplicate retry behavior."
        fix_steps.extend(
            [
                "Check payment provider status and failed transaction logs.",
                "Verify idempotency handling before retrying failed operations.",
            ]
        )
        warnings.append("Do not replay payment requests without idempotency guarantees.")

    if "gateway" in combined or "rate limit" in combined:
        issue_parts.append("gateway policy or routing issue")
        if severity == "low":
            severity = "medium"
        likely_cause = "Gateway routing, rate limiting, or auth propagation issue."
        fix_steps.extend(
            [
                "Review gateway logs for rejected requests and route mismatches.",
                "Validate rate-limit rules and auth header forwarding.",
            ]
        )

    if "auth" in combined or "token" in combined or "jwt" in combined:
        issue_parts.append("authentication failure")
        severity = "high" if "token" in combined or "jwt" in combined else severity
        likely_cause = "Expired credentials, auth middleware regression, or invalid token propagation."
        fix_steps.extend(
            [
                "Verify token issuance, expiry, and downstream auth validation.",
                "Check recent auth config or secret rotation changes.",
            ]
        )

    if not issue_parts:
        issue = "General service incident requiring investigation."
        fix_steps = [
            "Collect logs, request IDs, and timestamps for the failing path.",
            "Check recent deploys, config changes, and upstream dependency health.",
            "Escalate to the owning service team with captured evidence.",
        ]
        warnings = []
    else:
        issue = f"Incident indicates {'; '.join(issue_parts)}."

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
