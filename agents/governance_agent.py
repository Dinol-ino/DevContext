from fastapi import APIRouter
from pydantic import BaseModel, Field

try:
    from .tools import detect_conflict
except ImportError:
    from tools import detect_conflict

router = APIRouter(tags=["Governance"])


class GovernanceCheckRequest(BaseModel):
    diff_text: str = Field(..., min_length=1, examples=["moved rate limiting to payment service"])


class GovernanceCheckResponse(BaseModel):
    has_conflicts: bool
    comment_text: str


@router.post("/governance/check", response_model=GovernanceCheckResponse)
def check(payload: GovernanceCheckRequest) -> GovernanceCheckResponse:
    result = detect_conflict(payload.diff_text)
    return GovernanceCheckResponse(**result)
