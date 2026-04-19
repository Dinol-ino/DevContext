from fastapi import APIRouter

router = APIRouter()

@router.post("/governance/check")
def check():
    return {"status": "governance endpoint live"}