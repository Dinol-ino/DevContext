from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

try:
    from .tools import analyze_incident
except ImportError:
    from tools import analyze_incident

router = APIRouter(tags=["Incident"])


class IncidentRequest(BaseModel):
    alert_title: str = Field(default="", examples=["Payment API latency spike"])
    service_name: str = Field(default="", examples=["payments"])
    error_snippet: str = Field(default="", examples=["db connections exhausted"])


class IncidentResponse(BaseModel):
    issue: str
    severity: str
    likely_cause: str
    fix_steps: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


@router.post("/incident", response_model=IncidentResponse)
def incident(payload: IncidentRequest) -> IncidentResponse:
    try:
        result = analyze_incident(
            alert_title=payload.alert_title,
            service_name=payload.service_name,
            error_snippet=payload.error_snippet,
        )
        return IncidentResponse(**result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to analyze incident: {exc}") from exc
