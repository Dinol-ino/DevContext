from fastapi import APIRouter
from db import supabase

router = APIRouter()

@router.post("/ask")
def ask():
    data = supabase.table("nodes").select("*").limit(5).execute()

    return {
        "answer": "Fetched nodes",
        "data": data.data
    }