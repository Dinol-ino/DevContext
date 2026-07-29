#!/usr/bin/env python3
"""
DevContextIQ — Dynamic Test Suite for Repository: https://github.com/Dinol-ino/DFRAG
Automatically creates & confirms a test user via Supabase Auth Admin API to obtain a valid JWT session token.
"""

import sys
import json
import os
import time
import requests

# Ensure stdout uses UTF-8 encoding on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000/api/v1")
HEALTH_URL = "http://127.0.0.1:8000/health"
TARGET_REPO_URL = "https://github.com/Dinol-ino/DFRAG"
TARGET_REPO_ID = "Dinol-ino/DFRAG"

# Load environment variables from .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

sys.path.insert(0, ".")
try:
    from agents.db import get_client
except ImportError:
    get_client = lambda: None


def obtain_supabase_user_token():
    """Obtain a valid Supabase user JWT token by creating & confirming a test user via Admin API."""
    if len(sys.argv) > 1 and sys.argv[1].startswith("ey"):
        return sys.argv[1]

    env_token = os.getenv("SUPABASE_TOKEN")
    if env_token and env_token.startswith("ey"):
        return env_token

    client = get_client()
    if not client:
        return None

    email = os.getenv("TEST_USER_EMAIL", "dfrag.tester@devcontextiq.com")
    password = os.getenv("TEST_USER_PASSWORD", "TestPassword123!")

    # Admin create user with auto email confirmation
    try:
        client.auth.admin.create_user({
            "email": email,
            "password": password,
            "email_confirm": True
        })
    except Exception:
        pass

    # Sign in with password
    try:
        res = client.auth.sign_in_with_password({"email": email, "password": password})
        if res and res.session and res.session.access_token:
            return res.session.access_token
    except Exception as exc:
        print(f"Auth sign-in attempt warning: {exc}")

    return None


TOKEN = obtain_supabase_user_token()
HEADERS = {}
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"

print("=" * 80)
print(f" DevContextIQ End-to-End Test Suite for Target Repo: {TARGET_REPO_ID}")
print(f" Target API Base URL: {BASE_URL}")
print(f" Valid User Bearer Token: {'OBTAINED' if TOKEN else 'NOT OBTAINED (Ensure Supabase SQL schema & tables are created)'}")
print("=" * 80)

# Check health first
try:
    resp = requests.get(HEALTH_URL, timeout=5)
    print(f"\n[1/10] Server Health Check: HTTP {resp.status_code} -> {resp.json()}")
except Exception as e:
    print(f"\n[FAIL] Server Health Check Failed: {e}")
    print("\nNote: Make sure uvicorn backend server is started in another terminal:")
    print("      python -m uvicorn agents.main:app --reload --port 8000\n")


def run_test(test_name, method, endpoint, payload=None, params=None):
    url = f"{BASE_URL}{endpoint}" if endpoint.startswith("/") else f"{BASE_URL}/{endpoint}"
    print(f"\n----------------------------------------------------------------------")
    print(f"TESTING: {test_name}")
    print(f"   {method} {url}")
    if payload:
        print(f"   Payload: {json.dumps(payload, indent=2)[:300]}")
    
    start_time = time.time()
    try:
        req_headers = HEADERS.copy()
        if payload:
            req_headers["Content-Type"] = "application/json"

        if method.upper() == "GET":
            response = requests.get(url, headers=req_headers, params=params, timeout=120)
        elif method.upper() == "POST":
            response = requests.post(url, headers=req_headers, json=payload, timeout=120)
        elif method.upper() == "DELETE":
            response = requests.delete(url, headers=req_headers, timeout=30)
        else:
            raise ValueError(f"Unsupported method: {method}")
        
        duration = round(time.time() - start_time, 3)
        print(f"   Status Code: HTTP {response.status_code} ({duration}s)")
        
        try:
            data = response.json()
            print(f"   Response Summary:\n{json.dumps(data, indent=2)[:600]}")
        except Exception:
            print(f"   Raw Response Text: {response.text[:300]}")
            
        if response.status_code in (200, 201):
            print(f"[OK] PASSED: {test_name}")
            return True, response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text
        else:
            print(f"[FAIL] FAILED: {test_name} returned HTTP {response.status_code}")
            return False, response.text
    except Exception as exc:
        duration = round(time.time() - start_time, 3)
        print(f"[FAIL] ERROR: {test_name} threw an exception after {duration}s: {exc}")
        return False, str(exc)


# --- Step 1: Import Repository metadata and create embeddings ---
print("\n" + "=" * 80)
print(f" STAGE 1: Importing Repository {TARGET_REPO_URL}")
print("=" * 80)
ok_import, import_res = run_test(
    "1. Repository Import & Code Chunking",
    "POST",
    "/repo/import",
    payload={"repository_url": TARGET_REPO_URL, "branch": "main"}
)

# --- Step 2: List Repositories ---
ok_list, list_res = run_test(
    "2. List Workspace Repositories",
    "GET",
    "/repo/list"
)

# --- Step 3: Context RAG Querying ---
print("\n" + "=" * 80)
print(f" STAGE 2: Context RAG Assistant Query for {TARGET_REPO_ID}")
print("=" * 80)
ok_ask, ask_res = run_test(
    "3. Context RAG Query (/ask)",
    "POST",
    "/ask",
    payload={
        "question": "What is the architecture and main function of the DFRAG repository?",
        "repo_id": TARGET_REPO_ID,
        "max_context_chunks": 5
    }
)

# --- Step 4: Persistent Chat Memory ---
print("\n" + "=" * 80)
print(" STAGE 3: Multi-Thread Chat Memory")
print("=" * 80)
ok_thread, thread_res = run_test(
    "4. Create Chat Thread",
    "POST",
    "/chat/threads",
    payload={"repo_id": TARGET_REPO_ID, "title": "DFRAG Architectural Review"}
)

ok_threads_list, threads_list_res = run_test(
    "5. List Chat Threads",
    "GET",
    f"/chat/threads?repo_id={TARGET_REPO_ID}"
)

# --- Step 5: Automated PR Governance Check ---
print("\n" + "=" * 80)
print(" STAGE 4: Automated PR Governance & Merge Risk Check")
print("=" * 80)
diff_sample = (
    "diff --git a/main.py b/main.py\n"
    "index 1234567..89abcdef 100644\n"
    "--- a/main.py\n"
    "+++ b/main.py\n"
    "@@ -10,6 +10,8 @@\n"
    "+ def bypass_security_validation():\n"
    "+     # Disabling rate limit and token checks for high throughput\n"
    "+     pass\n"
)
ok_gov, gov_res = run_test(
    "6. Governance PR Diff Check",
    "POST",
    "/governance/check",
    payload={
        "pr_url": "https://github.com/Dinol-ino/DFRAG/pull/1",
        "diff_text": diff_sample
    }
)

# --- Step 6: Operational Incident Analysis ---
print("\n" + "=" * 80)
print(" STAGE 5: Operational Incident Diagnosis")
print("=" * 80)
ok_inc, inc_res = run_test(
    "7. Incident Analysis",
    "POST",
    "/incident",
    payload={
        "title": "High latency in embedding retrieval worker",
        "service_name": "dfrag-retriever",
        "stacktrace": "TimeoutError: Vector search request exceeded 5000ms threshold"
    }
)

# --- Step 7: Commit Intelligence ---
print("\n" + "=" * 80)
print(" STAGE 6: Commit Intelligence & Impact Analysis")
print("=" * 80)
ok_commit, commit_res = run_test(
    "8. Commit Impact Analysis",
    "POST",
    "/commit/analyze",
    payload={
        "repo_id": TARGET_REPO_ID,
        "commit_hash": "a1b2c3d4e5f67890",
        "commit_message": "Refactor vector indexing and upgrade sentence-transformers model",
        "diff_text": "+ EMBEDDING_DIM = 384\n- EMBEDDING_DIM = 768",
        "author": "dinol-ino"
    }
)

ok_commit_hist, commit_hist_res = run_test(
    "9. Fetch Commit History",
    "GET",
    f"/commit/history/{TARGET_REPO_ID.replace('/', '%2F')}"
)

# --- Step 8: Developer Onboarding Assistant ---
print("\n" + "=" * 80)
print(" STAGE 7: Developer Onboarding Assistant")
print("=" * 80)
ok_onboard, onboard_res = run_test(
    "10. Generate Onboarding Guide",
    "POST",
    "/onboarding/guide",
    payload={
        "repo_id": TARGET_REPO_ID,
        "role": "backend"
    }
)

ok_onboard_ov, onboard_ov_res = run_test(
    "11. Fetch Onboarding Overview",
    "GET",
    f"/onboarding/overview/{TARGET_REPO_ID.replace('/', '%2F')}"
)

# --- Step 9: Context Timeline ---
print("\n" + "=" * 80)
print(" STAGE 8: Context Timeline")
print("=" * 80)
ok_timeline, timeline_res = run_test(
    "12. Fetch Repository Context Timeline",
    "GET",
    f"/timeline/{TARGET_REPO_ID.replace('/', '%2F')}"
)

print("\n" + "=" * 80)
print(" TEST SUITE SUMMARY FOR REPOSITORY: Dinol-ino/DFRAG")
print("=" * 80)
results = [
    ("Repository Import", ok_import),
    ("Repository List", ok_list),
    ("Context RAG Ask", ok_ask),
    ("Chat Thread Creation", ok_thread),
    ("Governance PR Check", ok_gov),
    ("Incident Analysis", ok_inc),
    ("Commit Impact Analysis", ok_commit),
    ("Onboarding Guide", ok_onboard),
    ("Context Timeline", ok_timeline),
]

passed_count = sum(1 for _, ok in results if ok)
total_count = len(results)

for name, ok in results:
    status_str = "[OK] PASSED" if ok else "[FAIL] FAILED"
    print(f"  - {name:<30}: {status_str}")

print(f"\nFinal Score: {passed_count} / {total_count} Passed ({round(passed_count/total_count*100, 1)}%)")
print("=" * 80)
