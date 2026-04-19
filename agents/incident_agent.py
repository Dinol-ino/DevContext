from fastapi import APIRouter
from pydantic import BaseModel, Field

try:
    from .tools import analyze_incident
except ImportError:
    from tools import analyze_incident

router = APIRouter(tags=["Incident"])


class IncidentRequest(BaseModel):
    error: str = Field(..., min_length=1, examples=["db connections exhausted"])


class IncidentResponse(BaseModel):
    issue: str
    fix_steps: list[str] = Field(default_factory=list)


@router.post("/incident", response_model=IncidentResponse)
def incident(payload: IncidentRequest) -> IncidentResponse:
    result = analyze_incident(payload.error)
    return IncidentResponse(**result)
