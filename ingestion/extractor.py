import json
import os
import re
import time
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from .utils import clean_text, log_error, log_step, log_warning, safe_json

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
ALLOWED_KEYS = ("decision", "reason", "services", "risk")
OPENROUTER_TIMEOUT_SECONDS = 30
OPENROUTER_RETRIES = 2


def _fallback(reason: str, decision: str = "Unable to extract decision") -> dict[str, Any]:
    return {
        "decision": _normalize_label(decision),
        "reason": clean_text(reason),
        "services": [],
        "risk": "unknown",
    }


def _strip_code_fences(text: str) -> str:
    cleaned = clean_text(text)
    fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", cleaned, flags=re.IGNORECASE | re.DOTALL)
    if fence_match:
        return clean_text(fence_match.group(1))
    return cleaned.replace("```json", "").replace("```", "").strip()


def _sanitize_output(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}

    out["decision"] = _normalize_label(str(data.get("decision", "")))
    out["reason"] = clean_text(str(data.get("reason", "")))

    raw_services = data.get("services", [])
    services: list[str] = []
    if isinstance(raw_services, list):
        for item in raw_services:
            text = clean_text(str(item))
            if text:
                services.append(text)
    elif isinstance(raw_services, str):
        text = clean_text(raw_services)
        if text:
            services.append(text)
    out["services"] = services

    risk = clean_text(str(data.get("risk", "unknown"))).lower()
    out["risk"] = risk or "unknown"

    missing = [key for key in ALLOWED_KEYS if key not in out or out[key] in ("", None)]
    if missing:
        if "decision" in missing:
            out["decision"] = _normalize_label("Unable to extract decision")
        if "reason" in missing:
            out["reason"] = "Missing required keys from model output."
        if "services" in missing:
            out["services"] = []
        if "risk" in missing:
            out["risk"] = "unknown"

    return {key: out[key] for key in ALLOWED_KEYS}


def _normalize_label(label: str) -> str:
    normalized = clean_text(label)
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = normalized[:200].strip()
    if not normalized:
        return "Untitled decision"
    return normalized


def _payload_repo(payload: dict[str, Any]) -> str:
    return clean_text((payload.get("repository") or {}).get("full_name"))


def _payload_sender(payload: dict[str, Any]) -> str:
    sender = payload.get("sender") or {}
    return clean_text(sender.get("login") or sender.get("name"))


def _parse_push(payload: dict[str, Any]) -> dict[str, Any]:
    ref = clean_text(payload.get("ref"))
    branch = ref.split("/")[-1] if ref else "unknown"
    commits = payload.get("commits") or []
    messages = [clean_text(commit.get("message")) for commit in commits if clean_text(commit.get("message"))][:5]

    repo = _payload_repo(payload)
    author = clean_text((payload.get("pusher") or {}).get("name")) or _payload_sender(payload)
    source_url = clean_text(payload.get("compare")) or clean_text((payload.get("head_commit") or {}).get("url"))
    label = _normalize_label(f"Push to {branch} ({len(commits)} commit{'s' if len(commits) != 1 else ''})")
    summary = (
        f"Event: push\nRepo: {repo}\nBranch: {branch}\nAuthor: {author}\n"
        f"Commits: {len(commits)}\nMessages: {' | '.join(messages) if messages else 'none'}"
    )

    return {
        "event": "push",
        "label": label,
        "source_url": source_url,
        "repo": repo,
        "author": author,
        "services": [],
        "summary_text": summary,
        "metadata": {
            "event": "push",
            "branch": branch,
            "commit_count": len(commits),
            "commit_messages": messages,
        },
    }


def _parse_pull_request(payload: dict[str, Any]) -> dict[str, Any]:
    pr = payload.get("pull_request") or {}
    action = clean_text(payload.get("action"))
    merged = bool(pr.get("merged"))
    state = "merged" if action == "closed" and merged else (action or clean_text(pr.get("state")) or "updated")

    title = clean_text(pr.get("title")) or "Pull request update"
    body = clean_text(pr.get("body"))
    repo = _payload_repo(payload)
    author = clean_text((pr.get("user") or {}).get("login")) or _payload_sender(payload)
    source_url = clean_text(pr.get("html_url"))
    number = pr.get("number")
    label = _normalize_label(f"{title} [{state}]")
    summary = (
        f"Event: pull_request\nRepo: {repo}\nState: {state}\nTitle: {title}\n"
        f"Author: {author}\nBody: {body}\nURL: {source_url}"
    )

    return {
        "event": "pull_request",
        "label": label,
        "source_url": source_url,
        "repo": repo,
        "author": author,
        "services": [],
        "summary_text": summary,
        "metadata": {
            "event": "pull_request",
            "action": action,
            "state": state,
            "merged": merged,
            "number": number,
        },
    }


def _parse_review(payload: dict[str, Any], event_name: str) -> dict[str, Any]:
    review = payload.get("review") or {}
    comment = payload.get("comment") or {}
    pr = payload.get("pull_request") or {}
    repo = _payload_repo(payload)
    reviewer = clean_text((review.get("user") or {}).get("login")) or clean_text((comment.get("user") or {}).get("login")) or _payload_sender(payload)
    state = clean_text(review.get("state")) or clean_text(payload.get("action")) or "commented"
    pr_title = clean_text(pr.get("title")) or "Pull request"
    source_url = clean_text(review.get("html_url")) or clean_text(comment.get("html_url")) or clean_text(pr.get("html_url"))
    label = _normalize_label(f"{event_name} by {reviewer or 'unknown'} [{state}]")
    summary = (
        f"Event: {event_name}\nRepo: {repo}\nReviewer: {reviewer}\nState: {state}\n"
        f"PR: {pr_title}\nURL: {source_url}"
    )

    return {
        "event": event_name,
        "label": label,
        "source_url": source_url,
        "repo": repo,
        "author": reviewer,
        "services": [],
        "summary_text": summary,
        "metadata": {
            "event": event_name,
            "reviewer": reviewer,
            "state": state,
            "pr_title": pr_title,
        },
    }


def _parse_commit_comment(payload: dict[str, Any]) -> dict[str, Any]:
    comment = payload.get("comment") or {}
    repo = _payload_repo(payload)
    author = clean_text((comment.get("user") or {}).get("login")) or _payload_sender(payload)
    source_url = clean_text(comment.get("html_url")) or clean_text(comment.get("url"))
    body = clean_text(comment.get("body"))
    commit_id = clean_text(comment.get("commit_id"))
    label = _normalize_label(f"commit_comment by {author or 'unknown'}")
    summary = (
        f"Event: commit_comment\nRepo: {repo}\nAuthor: {author}\nCommit: {commit_id}\n"
        f"Comment: {body}\nURL: {source_url}"
    )

    return {
        "event": "commit_comment",
        "label": label,
        "source_url": source_url,
        "repo": repo,
        "author": author,
        "services": [],
        "summary_text": summary,
        "metadata": {
            "event": "commit_comment",
            "commit_id": commit_id,
        },
    }


def _parse_repository(payload: dict[str, Any]) -> dict[str, Any]:
    repository = payload.get("repository") or {}
    action = clean_text(payload.get("action")) or "updated"
    repo_name = clean_text(repository.get("full_name")) or clean_text(repository.get("name"))
    private = bool(repository.get("private"))
    visibility = "private" if private else "public"
    source_url = clean_text(repository.get("html_url"))
    label = _normalize_label(f"Repository {action}: {repo_name}")
    summary = (
        f"Event: repository\nRepo: {repo_name}\nAction: {action}\nVisibility: {visibility}\nURL: {source_url}"
    )

    changes = payload.get("changes")
    changed_fields = list(changes.keys()) if isinstance(changes, dict) else []

    return {
        "event": "repository",
        "label": label,
        "source_url": source_url,
        "repo": repo_name,
        "author": _payload_sender(payload),
        "services": [],
        "summary_text": summary,
        "metadata": {
            "event": "repository",
            "action": action,
            "visibility": visibility,
            "changed_fields": changed_fields,
        },
    }


def _parse_unknown(payload: dict[str, Any], event_name: str) -> dict[str, Any]:
    repo = _payload_repo(payload)
    author = _payload_sender(payload)
    source_url = clean_text((payload.get("repository") or {}).get("html_url"))
    label = _normalize_label(f"GitHub event: {event_name or 'unknown'}")
    summary = f"Event: {event_name or 'unknown'}\nRepo: {repo}\nAuthor: {author}\nURL: {source_url}"
    return {
        "event": event_name or "unknown",
        "label": label,
        "source_url": source_url,
        "repo": repo,
        "author": author,
        "services": [],
        "summary_text": summary,
        "metadata": {"event": event_name or "unknown"},
    }


def parse_github_event(event_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    event = clean_text(event_name).lower()
    if event == "push":
        return _parse_push(payload)
    if event == "pull_request":
        return _parse_pull_request(payload)
    if event in {"pull_request_review", "pull_request_review_comment"}:
        return _parse_review(payload, event)
    if event == "commit_comment":
        return _parse_commit_comment(payload)
    if event == "repository":
        return _parse_repository(payload)

    log_warning(f"Using fallback parser for event={event or 'unknown'}")
    return _parse_unknown(payload, event)


def _build_prompt(pr_text: str) -> str:
    return (
        "You are extracting engineering decisions from pull request content.\n"
        "Return ONLY strict JSON with exactly these keys and no extras:\n"
        '{\"decision\": string, \"reason\": string, \"services\": list[str], \"risk\": string}\n'
        "Do not include markdown fences.\n\n"
        f"PR text:\n{pr_text}"
    )


def _call_openrouter(payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    last_error = "Unknown API failure"

    for attempt in range(OPENROUTER_RETRIES + 1):
        try:
            response = requests.post(
                OPENROUTER_URL,
                headers=headers,
                json=payload,
                timeout=OPENROUTER_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            last_error = str(exc)
            if attempt < OPENROUTER_RETRIES:
                log_step(f"OpenRouter request failed on attempt {attempt + 1}, retrying.")
                time.sleep(0.5 * (attempt + 1))
            else:
                log_error(f"OpenRouter request failed on final attempt: {exc}")

    raise RuntimeError(last_error)


def extract_decision(pr_text: str) -> dict:
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    model = os.getenv("OPENROUTER_MODEL", "").strip()

    if not api_key:
        return _fallback("OPENROUTER_API_KEY is not configured.")
    if not model:
        return _fallback("OPENROUTER_MODEL is not configured.")

    prompt = _build_prompt(clean_text(pr_text))
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        data = _call_openrouter(payload, headers)
    except Exception as exc:
        log_error(f"Decision extraction failed due to API error: {exc}")
        return _fallback(f"OpenRouter API failure: {exc}")

    content = (
        data.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    )
    cleaned = _strip_code_fences(content)
    if not cleaned:
        log_error("Decision extraction failed: empty model content.")
        return _fallback("OpenRouter returned empty content.")

    parsed = safe_json(cleaned)
    if not parsed:
        log_error("Decision extraction failed: invalid JSON from model.")
        return _fallback("Unable to parse model output as JSON.", decision="Parse fallback")

    # no hallucinated fields: explicitly keep only the required schema keys
    sanitized = _sanitize_output(parsed)
    return sanitized
