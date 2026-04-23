from fastapi import APIRouter, HTTPException
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
    severity: str
    matched_rules: list[str] = Field(default_factory=list)
    comment_text: str
    safe_to_merge: bool


@router.post("/governance/check", response_model=GovernanceCheckResponse)
def check(payload: GovernanceCheckRequest) -> GovernanceCheckResponse:
    try:
        result = detect_conflict(payload.diff_text)
        return GovernanceCheckResponse(**result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to run governance check: {exc}") from exc
