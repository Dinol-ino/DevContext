from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

try:
    from .tools import format_sources, search_nodes
except ImportError:
    from tools import format_sources, search_nodes

router = APIRouter(tags=["Context"])


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, examples=["Why rate limiting at gateway?"])


class Source(BaseModel):
    id: Any = None
    title: Optional[str] = None
    type: Optional[str] = None
    reason: Any = None
    services: Any = None
    url: Optional[str] = None


class AskResponse(BaseModel):
    answer: str
    confidence: float = Field(..., ge=0, le=1)
    sources: list[Source] = Field(default_factory=list)


def _build_answer(rows: list[dict[str, Any]]) -> tuple[str, float]:
    if not rows:
        return ("No matching decisions found for the question.", 0.0)

    top_rows = rows[:3]
    lines: list[str] = []
    scores = [float(row.get("_match_score", 0.0)) for row in top_rows]
    confidence = min(0.98, 0.45 + (max(scores) / 10.0 if scores else 0.0))

    for row in top_rows:
        label = str(row.get("label") or "Unnamed decision")
        metadata = row.get("metadata") or {}
        reason = metadata.get("reason") if isinstance(metadata, dict) else None
        services = metadata.get("services") if isinstance(metadata, dict) else None
        service_text = ", ".join(str(item) for item in services) if isinstance(services, list) and services else ""

        sentence = label
        if reason:
            sentence += f": {str(reason).strip()}"
        if service_text:
            sentence += f" Services: {service_text}."
        else:
            sentence += "."
        lines.append(sentence)

    answer = "Relevant decisions: " + " ".join(lines)
    return answer, round(confidence, 2)


@router.post("/ask", response_model=AskResponse)
def ask(payload: AskRequest) -> AskResponse:
    try:
        rows = search_nodes(payload.question)
        sources = format_sources(rows)
        answer, confidence = _build_answer(rows)
        return AskResponse(answer=answer, confidence=confidence, sources=sources)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to answer question: {exc}") from exc
