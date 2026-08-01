"""Quick smoke test for health routes plus optional authenticated agent routes."""

import json
import os

import requests

BASE = os.getenv("DEVCONTEXT_API_BASE_URL", "http://localhost:8000").rstrip("/")
TOKEN = os.getenv("DEVCONTEXT_BEARER_TOKEN", "").strip()


def build_headers():
    headers = {}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    return headers


def test(name, method, path, body=None):
    url = BASE + path
    try:
        r = requests.request(method, url, json=body, headers=build_headers(), timeout=30)
        print(f"\n[{name}] {method} {path} -> {r.status_code}")
        try:
            print(json.dumps(r.json(), indent=2)[:400])
        except Exception:
            print(r.text[:400])
    except Exception as exc:
        print(f"\n[{name}] ERROR: {exc}")


test("health", "GET", "/health")
test("api_health", "GET", "/api/v1/health")

if TOKEN:
    test("ask", "POST", "/api/v1/ask", {"question": "Why was rate limiting added at the gateway?"})
    test("governance", "POST", "/api/v1/governance/check", {"diff_text": "removed gateway rate limiting and moved auth checks to service layer"})
    test("incident", "POST", "/api/v1/incident", {"alert_title": "DB connections exhausted", "service_name": "payments", "error_snippet": "Too many connections"})
else:
    print("\nSkipping protected endpoint smoke checks. Set DEVCONTEXT_BEARER_TOKEN to exercise /ask, /governance/check, and /incident.")
