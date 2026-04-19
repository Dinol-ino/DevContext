import re
from typing import Any

try:
    from .db import get_supabase_client
except ImportError:
    from db import get_supabase_client


def _normalize_token(token: str) -> str:
    if token.endswith("ing") and len(token) > 5:
        return token[:-3]
    if token.endswith("s") and len(token) > 3:
        return token[:-1]
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


def search_nodes(question: str, limit: int = 5) -> list[dict[str, Any]]:
    client = get_supabase_client()
    if client is None:
        return []

    try:
        response = client.table("nodes").select("*").limit(200).execute()
    except Exception:
        return []

    rows: list[dict[str, Any]] = response.data or []
    if not rows:
        return []

    query_terms = _tokenize(question)
    if not query_terms:
        return []

    scored: list[tuple[float, dict[str, Any]]] = []

    for row in rows:
        searchable_fields = {
            "label": _normalize_value(row.get("label")),
            "type": _normalize_value(row.get("type")),
            "reason": _normalize_value(_metadata_value(row, "reason")),
            "services": _normalize_value(_metadata_value(row, "services")),
            "source_url": _normalize_value(row.get("source_url")),
        }

        score = 0.0
        for field, value in searchable_fields.items():
            field_terms = _tokenize(value)
            matches = query_terms.intersection(field_terms)
            if not matches:
                continue

            weight = {
                "label": 3.0,
                "type": 1.5,
                "reason": 2.5,
                "services": 2.0,
                "source_url": 1.0,
            }[field]
            score += len(matches) * weight

        combined_text = " ".join(searchable_fields.values()).lower()
        if question.lower().strip() in combined_text:
            score += 3.0

        if score > 0:
            scored.append((score, row))

    if scored:
        scored.sort(key=lambda item: item[0], reverse=True)
        return [row for _, row in scored[:limit]]

    return []


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
    text = diff_text.lower()
    rules = {
        "rate limit": "medium",
        "gateway": "medium",
        "auth": "high",
        "db": "high",
        "retry": "medium",
        "payment": "high",
        "token": "high",
        "cache": "low",
    }
    matched = [keyword for keyword in rules if keyword in text]

    if not matched:
        return {
            "has_conflicts": False,
            "severity": "low",
            "matched_rules": [],
            "comment_text": "No governance-sensitive changes detected.",
        }

    severity_rank = {"low": 1, "medium": 2, "high": 3}
    severity = max((rules[keyword] for keyword in matched), key=lambda item: severity_rank[item])

    return {
        "has_conflicts": True,
        "severity": severity,
        "matched_rules": matched,
        "comment_text": (
            f"Potential {severity} governance conflict detected for: "
            f"{', '.join(matched)}. Check related engineering decisions before merge."
        ),
    }


def analyze_incident(error: str) -> dict[str, Any]:
    text = error.lower()
    checks = {
        "db": {
            "severity": "high",
            "cause": "Database pressure, connection exhaustion, or slow queries.",
            "steps": [
                "Check connection pool usage and active DB sessions.",
                "Identify long-running queries and recent migrations.",
                "Temporarily reduce traffic or increase pool capacity if needed.",
            ],
            "warnings": ["Avoid blindly restarting services before preserving DB metrics."],
        },
        "timeout": {
            "severity": "medium",
            "cause": "Slow upstream dependency or timeout settings that are too aggressive.",
            "steps": [
                "Trace the slow request path using logs or APM spans.",
                "Check upstream latency and error rates.",
                "Tune retry and timeout settings after identifying the bottleneck.",
            ],
            "warnings": ["Retries can amplify traffic during an outage."],
        },
        "payment": {
            "severity": "high",
            "cause": "Payment provider failure, declined API calls, or unsafe retry behavior.",
            "steps": [
                "Check payment provider status and API error payloads.",
                "Verify idempotency keys are present on retryable requests.",
                "Review recent payment service deploys and config changes.",
            ],
            "warnings": ["Do not replay payment requests without idempotency guarantees."],
        },
        "gateway": {
            "severity": "medium",
            "cause": "Gateway routing, rate limiting, or upstream health-check issue.",
            "steps": [
                "Review gateway logs for rejected or misrouted requests.",
                "Check rate-limit rules and upstream health checks.",
                "Validate auth headers and route configuration.",
            ],
            "warnings": ["Gateway changes can affect multiple services at once."],
        },
    }

    matched = [keyword for keyword in checks if keyword in text]

    if not matched:
        return {
            "issue": "Unclassified incident signal. More context is required.",
            "severity": "low",
            "likely_cause": "The error does not match known incident keywords.",
            "fix_steps": [
                "Collect logs and request IDs from the failing flow.",
                "Check recent deploys and configuration changes.",
                "Escalate to the owning service team with evidence.",
            ],
            "warnings": [],
        }

    severity_rank = {"low": 1, "medium": 2, "high": 3}
    severity = max(
        (checks[keyword]["severity"] for keyword in matched),
        key=lambda item: severity_rank[item],
    )

    fix_steps: list[str] = []
    warnings: list[str] = []
    for keyword in matched:
        for step in checks[keyword]["steps"]:
            if step not in fix_steps:
                fix_steps.append(step)
        for warning in checks[keyword]["warnings"]:
            if warning not in warnings:
                warnings.append(warning)

    likely_causes = [checks[keyword]["cause"] for keyword in matched]

    return {
        "issue": f"Incident likely involves: {', '.join(matched)}.",
        "severity": severity,
        "likely_cause": " ".join(likely_causes),
        "fix_steps": fix_steps,
        "warnings": warnings,
    }
