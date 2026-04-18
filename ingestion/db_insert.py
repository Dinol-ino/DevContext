import os
from supabase import create_client
from dotenv import load_dotenv

load_dotenv("../.env")

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

supabase = create_client(url, key)


def insert_decision(data, source_url):
    payload = {
        "type": "decision",
        "label": data["decision"],
        "metadata": {
            "reason": data["reason"],
            "services": data["services"]
        },
        "source_url": source_url
    }

    result = supabase.table("nodes").insert(payload).execute()
    return result