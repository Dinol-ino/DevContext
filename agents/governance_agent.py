from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

try:
    from .prompts import GOVERNANCE_SYSTEM_PROMPT
    from .tools import call_llm, detect_conflict
except ImportError:
    from prompts import GOVERNANCE_SYSTEM_PROMPT
    from tools import call_llm, detect_conflict

router = APIRouter(tags=["Governance"])


class GovernanceCheckRequest(BaseModel):
    diff_text: str = Field(..., min_length=1, examples=["removed gateway rate limiting and moved auth checks"])


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

        llm_comment = call_llm(
            GOVERNANCE_SYSTEM_PROMPT,
            (
                f"Diff text:\n{payload.diff_text}\n\n"
                f"Matched rules: {', '.join(result['matched_rules'])}\n"
                f"Severity: {result['severity']}\n"
                f"Safe to merge: {result['safe_to_merge']}"
            ),
        )
        if llm_comment:
            result["comment_text"] = llm_comment

        return GovernanceCheckResponse(**result)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to run governance check: {exc}") from exc
