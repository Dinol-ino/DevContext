"""Quick smoke-test for all three agent API endpoints."""
import requests
import json

BASE = "http://localhost:8000"

def test(name, method, path, body=None):
    url = BASE + path
    try:
        r = requests.request(method, url, json=body, timeout=30)
        print(f"\n[{name}] {method} {path} -> {r.status_code}")
        try:
            print(json.dumps(r.json(), indent=2)[:400])
        except Exception:
            print(r.text[:400])
    except Exception as exc:
        print(f"\n[{name}] ERROR: {exc}")

test("health",     "GET",  "/health")
test("api_health", "GET",  "/api/v1/health")
test("ask",        "POST", "/api/v1/ask",
     {"question": "Why was rate limiting added at the gateway?"})
test("governance", "POST", "/api/v1/governance/check",
     {"diff_text": "removed gateway rate limiting and moved auth checks to service layer"})
test("incident",   "POST", "/api/v1/incident",
     {"alert_title": "DB connections exhausted", "service_name": "payments", "error_snippet": "Too many connections"})
