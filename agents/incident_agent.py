from fastapi import APIRouter

router = APIRouter()

@router.post("/incident")
def incident():
    return {"status": "incident endpoint live"}