import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv("../.env")

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

supabase = create_client(url, key)