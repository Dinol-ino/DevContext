import json
import os
import re
from typing import Any

import requests
from dotenv import load_dotenv

try:
    from .utils import clean_text, log_error, log_step, safe_json
except ImportError:
    from utils import clean_text, log_error, log_step, safe_json

load_dotenv("../.env")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
ALLOWED_KEYS = ("decision", "reason", "services", "risk")


def _fallback(reason: str, decision: str = "Unable to extract decision") -> dict[str, Any]:
    return {
        "decision": decision,
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

    out["decision"] = clean_text(str(data.get("decision", "")))
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
            out["decision"] = "Unable to extract decision"
        if "reason" in missing:
            out["reason"] = "Missing required keys from model output."
        if "services" in missing:
            out["services"] = []
        if "risk" in missing:
            out["risk"] = "unknown"

    return {key: out[key] for key in ALLOWED_KEYS}


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

    # retries=2 means two retries after the initial request (3 attempts total)
    for attempt in range(3):
        try:
            response = requests.post(
                OPENROUTER_URL,
                headers=headers,
                json=payload,
                timeout=30,
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            last_error = str(exc)
            if attempt < 2:
                log_step(f"OpenRouter request failed on attempt {attempt + 1}, retrying.")
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
