import re
from typing import Any

try:
    from .db import get_supabase_client
except ImportError:
    from db import get_supabase_client


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def search_nodes(question: str, limit: int = 5) -> list[dict[str, Any]]:
    client = get_supabase_client()
    if client is None:
        return []

    response = client.table("nodes").select("*").limit(200).execute()
    rows: list[dict[str, Any]] = response.data or []
    if not rows:
        return []

    query_terms = _tokenize(question)
    scored: list[tuple[int, dict[str, Any]]] = []

    for row in rows:
        row_text = " ".join(str(value) for value in row.values() if value is not None)
        row_terms = _tokenize(row_text)
        score = len(query_terms.intersection(row_terms))
        if score > 0:
            scored.append((score, row))

    if scored:
        scored.sort(key=lambda item: item[0], reverse=True)
        return [row for _, row in scored[:limit]]

    return rows[:limit]


def format_sources(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []

    for index, row in enumerate(rows, start=1):
        title = row.get("title") or row.get("name") or f"Decision {index}"
        body = (
            row.get("decision")
            or row.get("summary")
            or row.get("content")
            or row.get("description")
            or ""
        )
        snippet = str(body).strip()
        if len(snippet) > 220:
            snippet = f"{snippet[:217]}..."

        sources.append(
            {
                "id": row.get("id"),
                "title": title,
                "snippet": snippet,
            }
        )

    return sources


def detect_conflict(diff_text: str) -> dict[str, Any]:
    text = diff_text.lower()
    keywords = ["rate limit", "gateway", "auth", "db"]
    matched = [keyword for keyword in keywords if keyword in text]

    if not matched:
        return {
            "has_conflicts": False,
            "comment_text": "No governance-sensitive keywords were detected in the diff.",
        }

    return {
        "has_conflicts": True,
        "comment_text": (
            "Potential governance conflicts detected for: "
            f"{', '.join(matched)}. Verify ADR alignment before merge."
        ),
    }


def analyze_incident(error: str) -> dict[str, Any]:
    text = error.lower()
    matched: list[str] = []

    for keyword in ["db", "timeout", "payment", "gateway"]:
        if keyword in text:
            matched.append(keyword)

    if not matched:
        return {
            "issue": "Unclassified incident signal. More context is required.",
            "fix_steps": [
                "Collect logs and request IDs from the failing flow.",
                "Check recent deploys and configuration changes.",
                "Escalate to the owning service team with evidence.",
            ],
        }

    issue = f"Incident likely involves: {', '.join(matched)}."
    step_map = {
        "db": [
            "Inspect DB connection pool utilization and active sessions.",
            "Increase pool size or reduce long-running transactions.",
        ],
        "timeout": [
            "Trace slow upstream dependencies and increase observability.",
            "Tune timeout/retry settings to avoid cascading failures.",
        ],
        "payment": [
            "Verify payment provider status and API error responses.",
            "Enable idempotency safeguards on retry paths.",
        ],
        "gateway": [
            "Review gateway rate-limit and routing policies.",
            "Validate auth headers and upstream health checks.",
        ],
    }

    fix_steps: list[str] = []
    for keyword in matched:
        for step in step_map[keyword]:
            if step not in fix_steps:
                fix_steps.append(step)

    return {"issue": issue, "fix_steps": fix_steps}
