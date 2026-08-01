import os

import requests
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

url = os.getenv("SUPABASE_URL", "")
key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY", "")
email = os.getenv("DEVCONTEXT_TEST_EMAIL", "").strip()
password = os.getenv("DEVCONTEXT_TEST_PASSWORD", "").strip()
base_url = os.getenv("DEVCONTEXT_API_BASE_URL", "http://localhost:8000/api/v1").strip().rstrip("/")

if not url or not key:
    print("ERROR: SUPABASE_URL and SUPABASE_KEY/SUPABASE_SERVICE_ROLE_KEY must be set.")
    raise SystemExit(1)

if not email or not password:
    print("ERROR: DEVCONTEXT_TEST_EMAIL and DEVCONTEXT_TEST_PASSWORD must be set for live endpoint checks.")
    raise SystemExit(1)

supabase = create_client(url, key)

print("Signing in/up user...")
try:
    res = supabase.auth.sign_in_with_password({"email": email, "password": password})
    print("Sign in successful.")
except Exception as exc:
    print(f"Sign in failed, attempting sign up: {exc}")
    try:
        res = supabase.auth.sign_up({"email": email, "password": password})
        print("Sign up successful.")
    except Exception as exc2:
        print(f"Sign up also failed: {exc2}")
        raise SystemExit(1)

if not res.session or not res.session.access_token:
    print("ERROR: Supabase did not return a session token.")
    raise SystemExit(1)

token = res.session.access_token
headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json",
}

print("\n--- Testing GET /repo/list ---")
r = requests.get(f"{base_url}/repo/list", headers=headers, timeout=30)
print(f"Status: {r.status_code}")
try:
    print(r.json())
except Exception:
    print(r.text)

print("\n--- Testing POST /repo/import ---")
payload = {
    "repo_url": "https://github.com/octocat/Spoon-Knife",
    "branch": "main",
}
r = requests.post(f"{base_url}/repo/import", json=payload, headers=headers, timeout=90)
print(f"Status: {r.status_code}")
try:
    import_data = r.json()
    print("Import response contains metadata keys:")
    print(list(import_data.keys()))
    if "metadata" in import_data:
        meta = import_data["metadata"]
        print(f"Name: {meta.get('name')}")
        print(f"Owner: {meta.get('owner')}")
        print(f"Languages: {meta.get('languages')}")
        print(f"Frameworks: {meta.get('frameworks')}")
        print(f"Dependencies: {meta.get('dependencies')}")
        print(f"File Count: {meta.get('file_count')}")
        print(f"Directory Count: {meta.get('directory_count')}")
        print(f"Size: {meta.get('repository_size')} bytes")
        print(f"Entry points: {meta.get('entry_points')}")
        print(f"Config files: {meta.get('config_files')}")
        print(f"Tech stack: {meta.get('technology_stack')}")
        print(f"Tree structure type: {type(meta.get('tree'))}")
except Exception:
    print(r.text)

print("\n--- Testing GET /repo/list again ---")
r = requests.get(f"{base_url}/repo/list", headers=headers, timeout=30)
print(f"Status: {r.status_code}")
repo_id = None
try:
    repos = r.json()
    print(f"Found {len(repos)} repositories.")
    if repos:
        repo_id = repos[0]["id"]
        print(f"First repo ID: {repo_id}, Label: {repos[0]['label']}")
except Exception:
    print(r.text)

if repo_id:
    print(f"\n--- Testing DELETE /repo/{repo_id} ---")
    r = requests.delete(f"{base_url}/repo/{repo_id}", headers=headers, timeout=30)
    print(f"Status: {r.status_code}")
    print(r.json())
else:
    print("\nSkipping delete test as no repo_id was found.")
