from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field, model_validator

try:
    from .prompts import INCIDENT_SYSTEM_PROMPT
    from .tools import analyze_incident, call_llm, parse_json_response
    from .auth_utils import get_current_user
except ImportError:
    from prompts import INCIDENT_SYSTEM_PROMPT
    from tools import analyze_incident, call_llm, parse_json_response
    from auth_utils import get_current_user

router = APIRouter(tags=["Incident"])


class IncidentRequest(BaseModel):
    alert_title: str = Field(default="", examples=["500 errors rising"])
    service_name: str = Field(default="", examples=["api-gateway"])
    error_snippet: str = Field(default="", examples=["connection pool exhausted"])

    @model_validator(mode="after")
    def check_at_least_one_field(self) -> "IncidentRequest":
        if not self.alert_title.strip() and not self.service_name.strip() and not self.error_snippet.strip():
            raise ValueError("At least one of alert_title, service_name, or error_snippet must be provided and non-empty")
        return self


class IncidentResponse(BaseModel):
    issue: str
    severity: str
    likely_cause: str
    fix_steps: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


@router.post("/incident", response_model=IncidentResponse)
def incident(payload: IncidentRequest, current_user: dict = Depends(get_current_user)) -> IncidentResponse:
    try:
        result = analyze_incident(
            alert_title=payload.alert_title,
            service_name=payload.service_name,
            error_snippet=payload.error_snippet,
        )

        llm_text = call_llm(
            INCIDENT_SYSTEM_PROMPT,
            (
                "Return strict JSON with keys issue, severity, likely_cause, fix_steps, warnings.\n\n"
                f"Alert title: {payload.alert_title}\n"
                f"Service: {payload.service_name}\n"
                f"Error snippet: {payload.error_snippet}\n"
                f"Baseline analysis: {result}"
            ),
        )
        llm_data = parse_json_response(llm_text)
        if llm_data:
            result.update({key: value for key, value in llm_data.items() if key in result})

        return IncidentResponse(**result)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to analyze incident: {exc}") from exc
