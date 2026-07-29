import os
import requests
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

url = os.getenv("SUPABASE_URL", "")
key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY", "")

if not url or not key:
    print("ERROR: SUPABASE_URL and SUPABASE_KEY/SUPABASE_SERVICE_ROLE_KEY must be set.")
    exit(1)

# Create supabase client
supabase = create_client(url, key)

email = "test_user_2026@gmail.com"
password = "superSecurePassword123!"

print("Signing in/up user...")
try:
    # Try signing in
    res = supabase.auth.sign_in_with_password({"email": email, "password": password})
    print("Sign in successful.")
except Exception as exc:
    print(f"Sign in failed, attempting sign up: {exc}")
    try:
        res = supabase.auth.sign_up({"email": email, "password": password})
        print("Sign up successful.")
    except Exception as exc2:
        print(f"Sign up also failed: {exc2}")
        exit(1)

token = res.session.access_token
headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}

BASE_URL = "http://localhost:8000/api/v1"

# 1. Test Listing Repositories
print("\n--- Testing GET /repo/list ---")
r = requests.get(f"{BASE_URL}/repo/list", headers=headers)
print(f"Status: {r.status_code}")
try:
    print(r.json())
except Exception:
    print(r.text)

# 2. Test Importing Repository (we use a small public repository for speed)
# Let's use a tiny public repo, e.g. https://github.com/octocat/Spoon-Knife
print("\n--- Testing POST /repo/import ---")
payload = {
    "repo_url": "https://github.com/octocat/Spoon-Knife",
    "branch": "main"
}
r = requests.post(f"{BASE_URL}/repo/import", json=payload, headers=headers)
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

# 3. Test List Again
print("\n--- Testing GET /repo/list again ---")
r = requests.get(f"{BASE_URL}/repo/list", headers=headers)
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

# 4. Test Deleting Repository
if repo_id:
    print(f"\n--- Testing DELETE /repo/{repo_id} ---")
    r = requests.delete(f"{BASE_URL}/repo/{repo_id}", headers=headers)
    print(f"Status: {r.status_code}")
    print(r.json())
else:
    print("\nSkipping delete test as no repo_id was found.")
